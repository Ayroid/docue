"""The access rule, over every combination of inputs, with no database.

`app/access/templates.py` expresses one rule three times -- as Python over rows
in hand, as a SQLAlchemy filter for the paginated listing, and as raw SQL for the
ranked search -- because each caller needs it in a different form. Three copies
of a security decision is a standing hazard, so this suite exists to make them
provably the same rule rather than three rules that happen to agree today.

**Why no database.** The decision half is pure functions over plain attributes,
which is what lets the whole case matrix run in milliseconds and in CI with no
Postgres. The two SQL forms cannot be *evaluated* here, so they are checked
structurally -- which clauses appear for which class of caller, and that the
caller's id is bound rather than interpolated. `scripts/check_access_control.py`
is the other half: it exercises all three against a real database over HTTP.

**The regression guard is the most important test in the file.**
`test_public_templates_behave_exactly_as_before` re-implements the rule as it
stood before `visibility` existed and asserts the new code agrees with it on
every input, for every public template. Every row in this database is public
until an admin says otherwise, so that equivalence is the claim that adding
access control changed nothing for anyone.
"""

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.access.templates import (
    access_ok,
    approval_ok,
    can_view_version,
    narrows_visibility,
    search_predicate,
    visible_templates_filter,
)
from app.models.template import VISIBILITY_PUBLIC, VISIBILITY_RESTRICTED, Template
from app.models.template_version import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    TemplateVersion,
)
from app.models.user import ROLE_ADMIN, ROLE_USER, User

APPROVALS = (APPROVAL_APPROVED, APPROVAL_PENDING, APPROVAL_REJECTED)
VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_RESTRICTED)

# Real model classes rather than stand-ins, deliberately: an attribute renamed on
# `Template` should break this suite, and a namespace built by hand would keep
# passing against a column that no longer exists.
OWNER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SUBMITTER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
STRANGER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ADMIN_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
TEMPLATE_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def user(user_id: uuid.UUID, role: str = ROLE_USER) -> User:
    return User(id=user_id, email=f"{user_id}@example.com", username=str(user_id), role=role)


def template(visibility: str = VISIBILITY_PUBLIC, owner_id=OWNER_ID, status: str = "active"):
    return Template(
        id=TEMPLATE_ID,
        title="MOM Form",
        original_filename="mom.xlsx",
        format="xlsx",
        status=status,
        visibility=visibility,
        owner_id=owner_id,
    )


def version(approval: str = APPROVAL_APPROVED, submitted_by=SUBMITTER_ID) -> TemplateVersion:
    return TemplateVersion(
        id=uuid.uuid4(),
        template_id=TEMPLATE_ID,
        version_number=1,
        approval_status=approval,
        submitted_by=submitted_by,
    )


OWNER = user(OWNER_ID)
SUBMITTER = user(SUBMITTER_ID)
STRANGER = user(STRANGER_ID)
ADMIN = user(ADMIN_ID, ROLE_ADMIN)
CALLERS = {"anonymous": None, "owner": OWNER, "submitter": SUBMITTER, "stranger": STRANGER,
           "admin": ADMIN}


class ExplodingSession:
    """A session that fails if anything is asked of it.

    Used to prove the grant lookup is skipped rather than merely cheap: a public
    template is the overwhelmingly common request, and one extra query on it
    would be a real cost paid on every card of every page.
    """

    def query(self, *args, **kwargs):  # pragma: no cover - the point is not to reach it
        raise AssertionError("the grant table was queried when it could not matter")

    def get(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("the session was used when it could not matter")


# ── the access half ────────────────────────────────────────────────────────


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_public_is_visible_to_everyone_including_anonymous(caller: str) -> None:
    """`public` is the pre-existing rule and must not have narrowed."""
    assert access_ok(CALLERS[caller], template(VISIBILITY_PUBLIC), has_grant=False) is True


@pytest.mark.parametrize(
    ("caller", "has_grant", "expected"),
    [
        ("anonymous", False, False),
        ("anonymous", True, False),  # nobody can hold a grant without an account
        ("owner", False, True),  # never locked out of your own upload
        ("admin", False, True),  # an admin who cannot open it cannot review it
        ("stranger", False, False),
        ("stranger", True, True),  # the grant is the only thing that changes this
        ("submitter", False, False),  # submitting a version is not access to the template
        ("submitter", True, True),
    ],
)
def test_restricted_access(caller: str, has_grant: bool, expected: bool) -> None:
    assert (
        access_ok(CALLERS[caller], template(VISIBILITY_RESTRICTED), has_grant=has_grant)
        is expected
    )


def test_restricted_with_no_owner_is_admin_and_grant_only() -> None:
    """A template that predates accounts has `owner_id IS NULL`.

    `None == None` is True in Python, so an `owner_id is None` check written
    carelessly would hand every ownerless restricted template to any caller
    whose own id was somehow null. Asserted rather than assumed.
    """
    ownerless = template(VISIBILITY_RESTRICTED, owner_id=None)
    assert access_ok(STRANGER, ownerless, has_grant=False) is False
    assert access_ok(ADMIN, ownerless, has_grant=False) is True
    assert access_ok(STRANGER, ownerless, has_grant=True) is True


# ── the approval half ──────────────────────────────────────────────────────


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_approved_version_passes_approval_for_everyone(caller: str) -> None:
    assert approval_ok(CALLERS[caller], template(), version(APPROVAL_APPROVED)) is True


@pytest.mark.parametrize("approval", [APPROVAL_PENDING, APPROVAL_REJECTED])
@pytest.mark.parametrize(
    ("caller", "expected"),
    [("anonymous", False), ("owner", True), ("submitter", True), ("stranger", False),
     ("admin", True)],
)
def test_unapproved_version_is_owner_submitter_admin_only(
    approval: str, caller: str, expected: bool
) -> None:
    assert approval_ok(CALLERS[caller], template(), version(approval)) is expected


def test_missing_version_is_owner_and_admin_only() -> None:
    """`current_version_id` can be null mid-upload; nothing published means
    nothing to show, but the owner still has to see their own row."""
    assert approval_ok(None, template(), None) is False
    assert approval_ok(STRANGER, template(), None) is False
    assert approval_ok(OWNER, template(), None) is True
    assert approval_ok(ADMIN, template(), None) is True


# ── the two halves composed ───────────────────────────────────────────────


def test_deleted_template_is_invisible_to_everyone() -> None:
    deleted = template(status="deleted")
    for caller in CALLERS.values():
        assert can_view_version(ExplodingSession(), caller, deleted, version()) is False


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("approval", APPROVALS)
def test_public_template_never_queries_the_grant_table(caller: str, approval: str) -> None:
    """The short-circuit in `can_view_version`, asserted rather than trusted."""
    can_view_version(
        ExplodingSession(), CALLERS[caller], template(VISIBILITY_PUBLIC), version(approval)
    )


def test_anonymous_caller_never_queries_the_grant_table() -> None:
    """Even on a restricted template: no account, no grant to find."""
    assert (
        can_view_version(ExplodingSession(), None, template(VISIBILITY_RESTRICTED), version())
        is False
    )


def test_both_gates_must_pass() -> None:
    """A grant does not publish an unapproved version, and approval does not
    open a restricted template. This is the property that keeps the two
    concepts independent."""

    class Granted:
        def query(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return (uuid.uuid4(),)

    granted = Granted()
    restricted = template(VISIBILITY_RESTRICTED)

    # Access yes, approval no.
    assert can_view_version(granted, STRANGER, restricted, version(APPROVAL_PENDING)) is False
    # Access yes, approval yes.
    assert can_view_version(granted, STRANGER, restricted, version(APPROVAL_APPROVED)) is True
    # Access no (no grant), approval yes.
    assert (
        can_view_version(ExplodingSession(), None, restricted, version(APPROVAL_APPROVED))
        is False
    )


# ── the regression guard ──────────────────────────────────────────────────


def rule_before_visibility_existed(
    caller: User | None, tmpl: Template, ver: TemplateVersion | None
) -> bool:
    """`templates.py::_visible_to`, verbatim, as it stood before this feature.

    Kept as a literal copy rather than imported: the point is to compare against
    what shipped, and importing the current implementation would make the
    comparison vacuous.
    """
    if ver is not None and ver.approval_status == APPROVAL_APPROVED:
        return True
    if caller is None:
        return False
    if caller.role == ROLE_ADMIN:
        return True
    return tmpl.owner_id == caller.id or (ver is not None and ver.submitted_by == caller.id)


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("approval", APPROVALS)
@pytest.mark.parametrize("owner_id", [OWNER_ID, None])
def test_public_templates_behave_exactly_as_before(
    caller: str, approval: str, owner_id
) -> None:
    """Adding access control changed nothing for any template nobody restricted.

    Every existing row is `public` -- the baseline migration defaults the
    column -- so this equivalence over the whole matrix is the no-regression
    claim for the entire corpus.
    """
    tmpl = template(VISIBILITY_PUBLIC, owner_id=owner_id)
    ver = version(approval)
    assert can_view_version(
        ExplodingSession(), CALLERS[caller], tmpl, ver
    ) is rule_before_visibility_existed(CALLERS[caller], tmpl, ver)


# ── the SQL forms ─────────────────────────────────────────────────────────


def compiled(expression) -> str:
    return str(expression.compile(dialect=postgresql.dialect()))


def test_listing_filter_matches_the_python_rule_by_caller_class() -> None:
    """`visible_templates_filter` cannot be evaluated without a database, so what
    is checked here is that each class of caller gets the clauses the Python rule
    would need -- and no more."""
    admin_sql = compiled(visible_templates_filter(ADMIN))
    assert "template_grants" not in admin_sql and "visibility" not in admin_sql

    anon_sql = compiled(visible_templates_filter(None))
    assert "visibility" in anon_sql
    # No account means no grant and no ownership; a filter that consulted either
    # would be dead SQL on every signed-out request.
    assert "template_grants" not in anon_sql and "owner_id" not in anon_sql

    user_sql = compiled(visible_templates_filter(STRANGER))
    for fragment in ("visibility", "owner_id", "template_grants", "expires_at"):
        assert fragment in user_sql, fragment


def test_search_predicate_by_caller_class() -> None:
    admin_sql, admin_params = search_predicate(ADMIN)
    assert "approval_status" in admin_sql
    assert "visibility" not in admin_sql and admin_params == {}

    anon_sql, anon_params = search_predicate(None)
    assert "visibility = 'public'" in anon_sql
    assert "template_grants" not in anon_sql and anon_params == {}

    user_sql, user_params = search_predicate(STRANGER)
    for fragment in ("visibility = 'public'", "owner_id = :access_uid", "template_grants",
                     "expires_at IS NULL"):
        assert fragment in user_sql, fragment
    assert user_params == {"access_uid": str(STRANGER_ID)}


def test_search_predicate_binds_the_caller_id_and_never_interpolates_it() -> None:
    """The one place in this feature where a caller-derived value meets raw SQL.

    A future edit that formats the id into the string would still pass every
    behavioural test in this file, so it is asserted directly.
    """
    sql, params = search_predicate(STRANGER)
    assert str(STRANGER_ID) not in sql
    assert params["access_uid"] == str(STRANGER_ID)
    assert sql.count(":access_uid") >= 2


def test_search_predicate_gates_both_halves_identically() -> None:
    """The fragment is dropped into the lexical and vector queries unchanged.

    `hybrid.py` builds both from the same string; this asserts the string itself
    carries no half-specific assumption, so it cannot be correct in one and
    wrong in the other.
    """
    sql, _ = search_predicate(STRANGER)
    assert sql.strip().startswith("AND")
    assert "SELECT" in sql.upper()
    # A stray semicolon or trailing clause would terminate the host query.
    assert ";" not in sql


def test_narrows_visibility_is_true_for_everyone_but_admins() -> None:
    """Drives the candidate-pool widening that compensates for HNSW
    post-filtering, so getting it backwards would silently weaken recall."""
    assert narrows_visibility(None) is True
    assert narrows_visibility(STRANGER) is True
    assert narrows_visibility(ADMIN) is False
