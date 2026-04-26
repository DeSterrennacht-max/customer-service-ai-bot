from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import FAQEntry
from backend.api.app.db.session import get_db
from backend.api.app.dependencies import ensure_tenant_access, get_accessible_bot_profile, get_current_user, is_super_admin
from backend.api.app.schemas.content import FAQCreate, FAQResponse, FAQUpdate
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.image_storage_service import ImageStorageError, ImageValidationError, ObjectImageStorageService

router = APIRouter(prefix="/admin/faqs", tags=["faqs"])
audit_service = AuditService()
image_storage_service = ObjectImageStorageService()


def raise_image_delete_error(exc: Exception) -> None:
    raise HTTPException(status_code=503, detail=str(exc)) from exc


def validate_image_assets_or_400(assets: object, tenant_id: UUID) -> list[dict[str, object]]:
    try:
        return image_storage_service.validate_assets_owned_by_tenant(assets, tenant_id)
    except ImageValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[FAQResponse])
def list_faqs(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
    bot_profile_id: str | None = None,
) -> list[FAQEntry]:
    statement = select(FAQEntry)
    if bot_profile_id:
        bot_profile = get_accessible_bot_profile(db, user, UUID(bot_profile_id))
        statement = statement.where(FAQEntry.bot_profile_id == bot_profile.id)
    elif not is_super_admin(user):
        statement = statement.where(FAQEntry.tenant_id == user.tenant_id)
    return list(db.scalars(statement.order_by(FAQEntry.priority.asc())).all())


@router.post("", response_model=FAQResponse)
def create_faq(
    payload: FAQCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> FAQEntry:
    bot_profile = get_accessible_bot_profile(db, user, payload.bot_profile_id)
    tenant_id = payload.tenant_id or bot_profile.tenant_id
    ensure_tenant_access(user, tenant_id)
    if tenant_id != bot_profile.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant and bot profile mismatch")
    payload_data = payload.model_dump(exclude={"tenant_id"})
    payload_data["image_assets_json"] = validate_image_assets_or_400(payload_data.get("image_assets_json"), tenant_id)
    faq = FAQEntry(tenant_id=tenant_id, **payload_data)
    db.add(faq)
    audit_service.record(
        db=db,
        tenant_id=str(faq.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="faq.created",
        target_type="faq_entry",
        detail_json={"bot_profile_id": str(faq.bot_profile_id)},
    )
    db.commit()
    db.refresh(faq)
    return faq


@router.patch("/{faq_id}", response_model=FAQResponse)
def update_faq(
    faq_id: str,
    payload: FAQUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> FAQEntry:
    faq = db.get(FAQEntry, UUID(faq_id))
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    ensure_tenant_access(user, faq.tenant_id)
    payload_data = payload.model_dump(exclude_unset=True)
    if "image_assets_json" in payload_data:
        payload_data["image_assets_json"] = validate_image_assets_or_400(payload_data.get("image_assets_json"), faq.tenant_id)
        try:
            image_storage_service.delete_removed_image_assets(faq.image_assets_json, payload_data["image_assets_json"])
        except (ImageStorageError, ImageValidationError) as exc:
            raise_image_delete_error(exc)
    for key, value in payload_data.items():
        setattr(faq, key, value)
    audit_service.record(
        db=db,
        tenant_id=str(faq.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="faq.updated",
        target_type="faq_entry",
        target_id=str(faq.id),
        detail_json=payload_data,
    )
    db.commit()
    db.refresh(faq)
    return faq


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_faq(
    faq_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> Response:
    faq = db.get(FAQEntry, UUID(faq_id))
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    ensure_tenant_access(user, faq.tenant_id)
    try:
        image_storage_service.delete_image_assets(faq.image_assets_json)
    except (ImageStorageError, ImageValidationError) as exc:
        raise_image_delete_error(exc)
    audit_service.record(
        db=db,
        tenant_id=str(faq.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="faq.deleted",
        target_type="faq_entry",
        target_id=str(faq.id),
        detail_json={"bot_profile_id": str(faq.bot_profile_id)},
    )
    db.delete(faq)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
