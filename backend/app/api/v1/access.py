"""Who may see which template. Admins only.

The administrative half of `app/access/templates.py`: that module *reads* the
rule on every request, this one writes it. Four routes, and the split between
them is the whole model -- `visibility` decides whether the grant list is
consulted at all, and the grants decide who is on it.

**Why admin-only rather than owner-too.** An owner can already see their own
template; letting them share it would make "who can see this document" a
decision distributed across everyone who ever uploaded one, which is the thing
doc control exists to avoid. `TemplateGrant.PERMISSION_MANAGE` is where
delegated re-sharing would land if that changes, and it is deliberately not
consulted yet -- see the model.

**Grants are kept when a template goes back to `public`.** They stop granting
anything, because `access_ok` short-circuits on `public` before it looks, but
they are not deleted: an admin who restricts, shares, opens up and re-restricts
should not have to rebuild the list from memory. The response says plainly that
a public template's grants are inactive.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import current_admin
from app.db.session import SessionLocal, get_db
from app.models.template import VISIBILITIES, Template
from app.models.template_grant import PERMISSIONS, TemplateGrant
from app.models.user import User
from app.notifications.service import create_notification, display_name
from app.schemas.access import GrantIn, GrantOut, TemplateAccessOut, VisibilityIn

logger = logging.getLogger("app.access")

router = APIRouter(prefix="/admin/templates", tags=["admin"])

KIND_TEMPLATE_SHARED = "template_shared"


def _template(db: Session, template_id: uuid.UUID) -> Template:
    """The template, whatever its visibility.

    No `can_view_*` call here on purpose: every route in this module already
    depends on `current_admin`, and an admin passes the access gate by
    definition. Routing an administrative read through the caller-facing gate
    would only invite the assumption that this module is safe for non-admins.
    """
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")
    return template


def _grant_out(grant: TemplateGrant, recipient: User, granter: User | None) -> GrantOut:
    now = datetime.now(timezone.utc)
    expires = grant.expires_at
    # A naive timestamp can come back from a column declared without a timezone
    # on some drivers; comparing it to an aware `now` raises rather than
    # returning False, which would turn the share dialog into a 500.
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return GrantOut(
        user_id=recipient.id,
        email=recipient.email,
        username=recipient.username,
        full_name=recipient.full_name,
        user_status=recipient.status,
        permission=grant.permission,
        granted_by=grant.granted_by,
        granted_by_name=display_name(granter) if granter is not None else None,
        granted_at=grant.granted_at,
        expires_at=grant.expires_at,
        expired=expires is not None and expires <= now,
    )


def _access_out(db: Session, template: Template) -> TemplateAccessOut:
    rows = (
        db.query(TemplateGrant, User)
        .join(User, User.id == TemplateGrant.user_id)
        .filter(TemplateGrant.template_id == template.id)
        .order_by(TemplateGrant.granted_at.desc())
        .all()
    )
    # One lookup for every granter named across the list rather than one per
    # row: an access list of twenty people shared by the same admin should not
    # cost twenty identical queries.
    granter_ids = {grant.granted_by for grant, _ in rows if grant.granted_by is not None}
    granters = (
        {u.id: u for u in db.query(User).filter(User.id.in_(granter_ids)).all()}
        if granter_ids
        else {}
    )
    owner = db.get(User, template.owner_id) if template.owner_id else None
    return TemplateAccessOut(
        template_id=template.id,
        title=template.title,
        visibility=template.visibility,
        owner_id=template.owner_id,
        owner_email=owner.email if owner else None,
        grants=[
            _grant_out(grant, recipient, granters.get(grant.granted_by))
            for grant, recipient in rows
        ],
    )


@router.get("/{template_id}/access", response_model=TemplateAccessOut)
def get_access(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(current_admin),
) -> TemplateAccessOut:
    """Current visibility and the full grant list."""
    return _access_out(db, _template(db, template_id))


@router.put("/{template_id}/visibility", response_model=TemplateAccessOut)
def set_visibility(
    template_id: uuid.UUID,
    payload: VisibilityIn,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> TemplateAccessOut:
    """Open a template to everyone, or close it to its grant list.

    Restricting a template with no grants yet is allowed and is not a mistake:
    "closed while I decide who needs it" is a real intention, and the opposite
    behaviour -- staying public until the first grant exists -- would leave a
    document exposed for exactly as long as it took to type an address.
    """
    if payload.visibility not in VISIBILITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown visibility '{payload.visibility}'. Use one of {sorted(VISIBILITIES)}.",
        )

    template = _template(db, template_id)
    if template.visibility != payload.visibility:
        template.visibility = payload.visibility
        db.commit()
        db.refresh(template)
        logger.info(
            "template %s set to %s by %s", template.id, payload.visibility, admin.username
        )
    return _access_out(db, template)


@router.post("/{template_id}/grants", response_model=TemplateAccessOut)
def grant_access(
    template_id: uuid.UUID,
    payload: GrantIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> TemplateAccessOut:
    """Give one registered address access to this template.

    Idempotent by design: sharing with someone who already has a grant updates
    their permission and expiry rather than adding a second row. Two rows would
    make "what can this person do" a question with more than one answer, which
    is why the unique constraint exists.
    """
    if payload.permission not in PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown permission '{payload.permission}'. Use one of {sorted(PERMISSIONS)}.",
        )

    template = _template(db, template_id)
    # Lowercased to match how `users.email` is stored -- the service layer
    # normalises on write, so an admin typing a capitalised address must not
    # produce "no account with that address".
    email = payload.email.strip().lower()
    recipient = db.query(User).filter(User.email == email).one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No account is registered to {email}. They need to sign up before a "
                "template can be shared with them."
            ),
        )
    if template.owner_id is not None and recipient.id == template.owner_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{display_name(recipient)} owns this template and can always see it. "
                "A grant would not change anything."
            ),
        )

    existing = (
        db.query(TemplateGrant)
        .filter(
            TemplateGrant.template_id == template.id,
            TemplateGrant.user_id == recipient.id,
        )
        .one_or_none()
    )
    if existing is not None:
        existing.permission = payload.permission
        existing.expires_at = payload.expires_at
        existing.granted_by = admin.id
        notify = False
    else:
        db.add(
            TemplateGrant(
                id=uuid.uuid4(),
                template_id=template.id,
                user_id=recipient.id,
                permission=payload.permission,
                granted_by=admin.id,
                expires_at=payload.expires_at,
            )
        )
        notify = True
    db.commit()
    db.refresh(template)

    logger.info(
        "template %s shared with %s by %s", template.id, recipient.email, admin.username
    )
    # Only on a genuinely new grant. Re-sending on every permission tweak would
    # train people to ignore the notification, and the second one carries no
    # news: they already had access.
    if notify:
        background_tasks.add_task(
            _announce_share, template.id, template.title, recipient.id, display_name(admin)
        )
    return _access_out(db, template)


@router.delete("/{template_id}/grants/{user_id}", response_model=TemplateAccessOut)
def revoke_access(
    template_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> TemplateAccessOut:
    """Take access away.

    **Documents this person already generated are not touched.** They are that
    person's own work product, recorded against them in `generated_documents`,
    and reaching back to delete or hide them would be a different and much
    larger promise than "they can no longer open the form". Losing access stops
    them starting anything new -- `_context_for` re-checks the template on every
    session turn, so an interview in progress stops at its next request too.
    """
    template = _template(db, template_id)
    grant = (
        db.query(TemplateGrant)
        .filter(TemplateGrant.template_id == template.id, TemplateGrant.user_id == user_id)
        .one_or_none()
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That person does not have a grant on this template.",
        )
    db.delete(grant)
    db.commit()
    db.refresh(template)
    logger.info("template %s access revoked for %s by %s", template.id, user_id, admin.username)
    return _access_out(db, template)


def _announce_share(
    template_id: uuid.UUID, title: str, recipient_id: uuid.UUID, granted_by_name: str
) -> None:
    """Tell the recipient, on its own session.

    A background task outlives the request and the `get_db` session that closed
    with it, so this opens its own -- the same pattern
    `templates.py::_announce_submission` uses and for the same reason. Failures
    are logged and swallowed: the grant is committed either way, and a template
    someone can now open matters more than the message saying so.
    """
    db = SessionLocal()
    try:
        create_notification(
            db,
            user_id=recipient_id,
            kind=KIND_TEMPLATE_SHARED,
            title="A template was shared with you",
            body=f'{granted_by_name} gave you access to "{title}".',
            template_id=template_id,
        )
        db.commit()
    except Exception:
        logger.exception("Failed to announce share of template %s", template_id)
        db.rollback()
    finally:
        db.close()
