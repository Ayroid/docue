"""The one place that answers "may this caller see this template?"

Every read path has to ask that question -- the library listing, the search box,
a region schema, a generation session, a version download -- and before this
module most of them did not. `templates.py::_visible_to` answered it for three
routes; five others reached the same rows and never asked:

* `POST /sessions` took a `template_id` with no authentication at all and
  fetched the stored bytes for it, which made every unapproved draft in the
  database readable by anyone who could guess a UUID.
* `GET /templates/{id}/regions` returned the complete document schema -- every
  region, every label -- for a version nobody had approved.
* `GET /templates/{id}/ingestion/{job}` reported on the same versions.
* `generate.py::_load` was reached by a route that required a user but checked
  nothing about *which* user, so any signed-in caller could download any
  version of any template.
* `versions.py` filtered versions by approval, correctly, but never asked
  whether the caller could see the template those versions belong to.

**Two independent gates, and both must pass.**

* *Access* is a property of the **template**: `visibility`, plus who owns it and
  who holds a grant. It answers "is this published *to you*?"
* *Approval* is a property of the **version**: `approval_status`, plus the
  owner/submitter exception. It answers "is this published *at all*?"

Keeping them apart is what lets an approved template be restricted, and a
restricted template be reviewed. Collapsing them would mean the only way to hide
a document was to refuse to approve it, and the only way to share one was to
publish it to everybody.

**The rule is expressed three times, which is the standing hazard here.**
`access_ok`/`approval_ok` decide about rows in hand; `visible_templates_filter`
is the same rule as a SQLAlchemy expression, because `GET /templates` paginates
and must filter in the database; `search_predicate` is the same rule again as
raw SQL, because `app/search/hybrid.py` ranks in the database and cannot filter
afterwards without corrupting its own top-k. They must agree, so the decision
half is written as **pure functions over plain attributes** -- no session, no
query -- and `tests/test_access_rule.py` walks the whole case matrix through all
three. If you change one, that suite fails until you change the others.

**404, never 403.** An error that distinguishes "forbidden" from "absent"
confirms the row exists, and its existence is part of what is being withheld.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, true
from sqlalchemy.orm import Session

from app.models.template import VISIBILITY_PUBLIC, Template
from app.models.template_grant import TemplateGrant
from app.models.template_version import APPROVAL_APPROVED, TemplateVersion
from app.models.user import ROLE_ADMIN, User

__all__ = [
    "TEMPLATE_NOT_FOUND",
    "access_ok",
    "approval_ok",
    "assert_can_view_template",
    "assert_can_view_version",
    "can_view_template",
    "can_view_version",
    "has_live_grant",
    "load_viewable",
    "search_predicate",
    "visible_templates_filter",
]

# Raised, never mutated, so one instance is safe to share -- the same pattern
# `api/deps.py` uses for `CREDENTIALS_EXCEPTION`. The wording is deliberately
# identical to a genuinely missing row.
TEMPLATE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Template not found."
)


# ── the rule, as pure functions ────────────────────────────────────────────
#
# Both take plain attributes off objects rather than a session, so they can be
# exercised over every combination of inputs without a database. That is not a
# testing convenience: it is the only way three expressions of one rule can be
# held to the same answer.


def access_ok(user: User | None, template: Template, *, has_grant: bool) -> bool:
    """The visibility half: is this template published to this caller at all?

    `public` is the rule that was in force before `visibility` existed, and it
    returns True for everyone including anonymous callers -- which is why adding
    this gate changed nothing for any template that was not deliberately
    restricted.

    The owner is never locked out of their own upload, and an admin is never
    locked out of anything: an admin who cannot open a restricted document
    cannot review it, and the approval queue would stall on the first one.
    """
    if template.visibility == VISIBILITY_PUBLIC:
        return True
    if user is None:
        return False
    if user.role == ROLE_ADMIN:
        return True
    if template.owner_id is not None and template.owner_id == user.id:
        return True
    return has_grant


def approval_ok(
    user: User | None, template: Template, version: TemplateVersion | None
) -> bool:
    """The approval half: is this version published, or is this caller entitled
    to see an unpublished one?

    Unchanged from the rule `templates.py::_visible_to` enforced before any of
    this moved: an approved version is fine for anyone who cleared `access_ok`,
    and an unapproved one is for the person who uploaded the template, the
    person who submitted that particular version, and admins. The submitter
    exception is what lets someone watch their own upload through review.
    """
    if version is not None and version.approval_status == APPROVAL_APPROVED:
        return True
    if user is None:
        return False
    if user.role == ROLE_ADMIN:
        return True
    if template.owner_id is not None and template.owner_id == user.id:
        return True
    return version is not None and version.submitted_by == user.id


# ── the same rule, over a session ──────────────────────────────────────────


def has_live_grant(db: Session, user: User, template: Template) -> bool:
    """Does `user` hold an unexpired grant on `template`?

    `expires_at IS NULL` means "no end date", which is the ordinary case. An
    expired row stops granting access without anyone sweeping the table, which
    is the whole reason the column is checked on every read rather than by a job.
    """
    now = datetime.now(timezone.utc)
    found = (
        db.query(TemplateGrant.id)
        .filter(
            TemplateGrant.template_id == template.id,
            TemplateGrant.user_id == user.id,
            or_(TemplateGrant.expires_at.is_(None), TemplateGrant.expires_at > now),
        )
        .first()
    )
    return found is not None


def can_view_version(
    db: Session, user: User | None, template: Template, version: TemplateVersion | None
) -> bool:
    """Whether `user` may see this particular version of `template`.

    Use this when the caller named a version -- a download, a region schema, an
    ingestion report. Asking about the *template* generally is
    `can_view_template`, which judges on whatever version is current.
    """
    if template.status == "deleted":
        return False
    # Only looked up when it can possibly matter. A public template needs no
    # grant and an anonymous caller can hold none, so the overwhelmingly common
    # request costs no extra query. The guard is deliberately conservative --
    # it never skips a lookup `access_ok` might need, it only skips ones whose
    # answer cannot change the outcome.
    has_grant = (
        template.visibility != VISIBILITY_PUBLIC
        and user is not None
        and has_live_grant(db, user, template)
    )
    if not access_ok(user, template, has_grant=has_grant):
        return False
    return approval_ok(user, template, version)


def can_view_template(db: Session, user: User | None, template: Template) -> bool:
    """Whether `user` may see this template at all, judged on its current version.

    A template with no current version is not viewable by anyone but its owner
    and an admin: it is mid-upload or broken, and either way there is nothing
    published to see.
    """
    version = (
        db.get(TemplateVersion, template.current_version_id)
        if template.current_version_id
        else None
    )
    return can_view_version(db, user, template, version)


def assert_can_view_version(
    db: Session, user: User | None, template: Template, version: TemplateVersion | None
) -> None:
    if not can_view_version(db, user, template, version):
        raise TEMPLATE_NOT_FOUND


def assert_can_view_template(db: Session, user: User | None, template: Template) -> None:
    if not can_view_template(db, user, template):
        raise TEMPLATE_NOT_FOUND


def load_viewable(
    db: Session,
    template_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    *,
    user: User | None,
) -> tuple[Template, TemplateVersion]:
    """The template plus one of its versions, defaulting to the current one, gated.

    A version is only ever reachable *through* its template, which is what stops
    a caller walking other templates' versions by guessing UUIDs -- the reason
    both `templates.py` and `generate.py` took `template_id` in the path even
    though `version_id` alone would have found the rows. Those two had grown
    identical copies of this loader with different gates on the end (one
    checked visibility, the other checked nothing); this is the merge of them.
    """
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise TEMPLATE_NOT_FOUND

    target_id = version_id or template.current_version_id
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template has no version."
        )
    version = db.get(TemplateVersion, target_id)
    if version is None or version.template_id != template_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found for this template.",
        )

    assert_can_view_version(db, user, template, version)
    return template, version


# ── the same rule, as a query filter ──────────────────────────────────────


def visible_templates_filter(user: User | None):
    """`access_ok` as a SQLAlchemy expression over `Template`.

    For `GET /templates`, which paginates: filtering a fetched page in Python
    would return short pages and skip templates entirely, so the access rule has
    to be part of the query that counts rows.

    Covers the *access* half only. The approval half stays where it already was
    in that route, because the listing's two modes disagree about it on purpose
    -- `mine=true` shows the caller their own pending uploads, the library view
    shows approved only.
    """
    if user is not None and user.role == ROLE_ADMIN:
        return true()
    public = Template.visibility == VISIBILITY_PUBLIC
    if user is None:
        return public
    grant = exists().where(
        and_(
            TemplateGrant.template_id == Template.id,
            TemplateGrant.user_id == user.id,
            or_(
                TemplateGrant.expires_at.is_(None),
                TemplateGrant.expires_at > datetime.now(timezone.utc),
            ),
        )
    )
    return or_(public, Template.owner_id == user.id, grant)


# ── the same rule, as raw SQL ─────────────────────────────────────────────

_APPROVED_SQL = """
  AND EXISTS (
        SELECT 1 FROM template_versions v
        WHERE v.id = templates.current_version_id
          AND v.approval_status = 'approved'
  )
"""

_ACCESSIBLE_SQL = """
  AND (
        templates.visibility = 'public'
     OR templates.owner_id = :access_uid
     OR EXISTS (
            SELECT 1 FROM template_grants g
            WHERE g.template_id = templates.id
              AND g.user_id = :access_uid
              AND (g.expires_at IS NULL OR g.expires_at > now())
        )
  )
"""

_PUBLIC_ONLY_SQL = """
  AND templates.visibility = 'public'
"""


def narrows_visibility(user: User | None) -> bool:
    """Whether `search_predicate` adds a clause beyond the approval gate.

    Read by `hybrid.search` to decide whether to widen its candidate pool. An
    admin's query is unnarrowed and needs no compensation; everyone else's is
    filtered after the index scan and can come back short.
    """
    return not (user is not None and user.role == ROLE_ADMIN)


def search_predicate(user: User | None) -> tuple[str, dict]:
    """The same rule as a SQL fragment, for the retrieval in `app/search/hybrid.py`.

    Returns `(sql, params)`. The SQL is a bare `AND ...` chain meant to be
    dropped into a `WHERE` on the `templates` table, and it is applied to *both*
    halves of the hybrid query -- an access gate on only one of them would leak
    through the other.

    **The approval half deliberately does not grant the owner/submitter
    exception that `approval_ok` does, and that is not drift.** Those exceptions
    exist so someone can follow their own upload through review; the places to do
    that are `GET /templates?mine=true` and the version history, both of which
    say so. Search ranks *the library*, and an unapproved draft is not in the
    library -- surfacing one among ranked results would put a document nobody has
    approved in front of a user who was looking for the approved one.

    **A caveat that matters for the vector half.** Postgres applies this
    predicate *after* the HNSW index scan, so a restricted-heavy corpus can
    return fewer than `candidates` rows and quietly weaken semantic recall for
    exactly the users the grants affect most. `hybrid.search` compensates by
    widening the candidate pool for non-admin callers; see the comment there.
    """
    if user is not None and user.role == ROLE_ADMIN:
        # An admin may see every template, so the access half is a tautology and
        # is left out rather than written as one -- it keeps the admin's query
        # identical to the one this module shipped with, and there is no clause
        # for the planner to work around.
        return _APPROVED_SQL, {}
    if user is None:
        return _APPROVED_SQL + _PUBLIC_ONLY_SQL, {}
    return _APPROVED_SQL + _ACCESSIBLE_SQL, {"access_uid": str(user.id)}
