"""A template's version history, and what each version changed.

The tracking half of version control. Approval itself lives in
`app/api/v1/admin.py` and the review state lives on `template_versions` -- this
adds no second source of truth for either, it reads them.

What it adds is the thing neither of those can answer: *what is different about
this version*. That comes from the `change_specs` row stored when the version
was compiled, so a history line can say "Venue set to Conference Room 4, typed
by the user" rather than "v7, 20.8 KB". See `app/services/changes.py` for the
limits of that claim.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.templates import assert_can_view_template
from app.api.deps import optional_user
from app.db.session import get_db
from app.models.template import Template
from app.models.template_version import APPROVAL_APPROVED, TemplateVersion
from app.models.user import ROLE_ADMIN, User
from app.schemas.version import VersionHistoryOut, VersionOut
from app.services.changes import changes_for_versions

logger = logging.getLogger("app.versions")

router = APIRouter(tags=["versions"])


def _usernames(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.username).where(User.id.in_(wanted))).all()
    return {r.id: r.username for r in rows}


@router.get("/templates/{template_id}/versions", response_model=VersionHistoryOut)
def version_history(
    template_id: uuid.UUID,
    include_unapproved: bool = Query(
        default=True,
        description="Pending and rejected versions. Visible to their submitter and to admins.",
    ),
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
) -> VersionHistoryOut:
    """Every version of this template, newest first, with what each one changed.

    Unapproved versions are filtered per caller rather than hidden outright: an
    admin sees the whole lineage because that is what reviewing means, and an
    author sees their own pending submission because otherwise it vanishes
    between submitting and being approved and looks lost. Everyone else sees the
    approved line, which is the template's actual history.
    """
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such template.")
    # Which *versions* to show is decided per caller below, and always was.
    # Whether the caller may see the template they belong to was not asked at
    # all, so a lineage -- titles, review notes, who submitted what and when --
    # came back for any template id.
    assert_can_view_template(db, user, template)

    versions = list(
        db.execute(
            select(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .order_by(TemplateVersion.version_number.desc())
        )
        .scalars()
        .all()
    )

    is_admin = user is not None and user.role == ROLE_ADMIN
    if not include_unapproved or not is_admin:
        versions = [
            v
            for v in versions
            if v.approval_status == APPROVAL_APPROVED
            or (include_unapproved and user is not None and v.submitted_by == user.id)
        ]

    changes = changes_for_versions(db, versions)
    names = _usernames(db, {v.submitted_by for v in versions} | {v.reviewed_by for v in versions})

    rows: list[VersionOut] = []
    for version in versions:
        record = changes[version.id]
        # Drift detection with no diffing at all: the `Ver.` the file claims
        # about itself against the number the hub gave it.
        claims = (version.in_doc_version or "").strip()
        claims_stale = bool(claims.isdigit() and int(claims) != version.version_number)
        rows.append(
            VersionOut(
                id=version.id,
                version_number=version.version_number,
                approval_status=version.approval_status,
                # Derived, not stored: a compiled version records the version it
                # came from, an upload has nothing to come from. That makes the
                # distinction a fact about the lineage rather than a duplicated
                # column that can disagree with it.
                origin="generated" if version.parent_version_id else "upload",
                is_current=template.current_version_id == version.id,
                created_at=version.created_at,
                submitted_by=version.submitted_by,
                submitted_by_name=names.get(version.submitted_by) if version.submitted_by else None,
                reviewed_by_name=names.get(version.reviewed_by) if version.reviewed_by else None,
                reviewed_at=version.reviewed_at,
                review_note=version.review_note,
                size_bytes=version.size_bytes,
                in_doc_version=version.in_doc_version,
                claims_stale_version=claims_stale,
                download_url=f"/api/v1/templates/{template_id}/versions/{version.id}/download",
                summary=record.summary,
                changed=[c.as_dict() for c in record.changed],
                dropped=record.dropped,
                protected_regions=record.protected_regions,
                qa_overall=record.qa_overall,
                intent=record.intent,
            )
        )

    return VersionHistoryOut(
        template_id=template.id,
        template_title=template.title,
        current_version_id=template.current_version_id,
        versions=rows,
    )
