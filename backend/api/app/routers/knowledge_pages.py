from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import KnowledgeChunk, KnowledgePage
from backend.api.app.db.session import get_db
from backend.api.app.dependencies import ensure_tenant_access, get_accessible_bot_profile, get_current_user, is_super_admin
from backend.api.app.schemas.content import KnowledgePageCreate, KnowledgePageResponse, KnowledgePageUpdate
from backend.api.app.services.audit_service import AuditService
from backend.api.app.services.image_storage_service import ImageStorageError, ImageValidationError, R2ImageStorageService
from backend.api.app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/admin/knowledge-pages", tags=["knowledge-pages"])
knowledge_service = KnowledgeService()
audit_service = AuditService()
image_storage_service = R2ImageStorageService()


def raise_image_delete_error(exc: Exception) -> None:
    raise HTTPException(status_code=503, detail=str(exc)) from exc


def validate_image_assets_or_400(assets: object, tenant_id: UUID) -> list[dict[str, object]]:
    try:
        return image_storage_service.validate_assets_owned_by_tenant(assets, tenant_id)
    except ImageValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[KnowledgePageResponse])
def list_knowledge_pages(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
    bot_profile_id: str | None = None,
) -> list[KnowledgePage]:
    statement = select(KnowledgePage)
    if bot_profile_id:
        bot_profile = get_accessible_bot_profile(db, user, UUID(bot_profile_id))
        statement = statement.where(KnowledgePage.bot_profile_id == bot_profile.id)
    elif not is_super_admin(user):
        statement = statement.where(KnowledgePage.tenant_id == user.tenant_id)
    return list(db.scalars(statement.order_by(KnowledgePage.updated_at.desc())).all())


@router.post("", response_model=KnowledgePageResponse)
def create_knowledge_page(
    payload: KnowledgePageCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> KnowledgePage:
    bot_profile = get_accessible_bot_profile(db, user, payload.bot_profile_id)
    tenant_id = payload.tenant_id or bot_profile.tenant_id
    ensure_tenant_access(user, tenant_id)
    if tenant_id != bot_profile.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant and bot profile mismatch")
    payload_data = payload.model_dump(exclude={"tenant_id"})
    payload_data["image_assets_json"] = validate_image_assets_or_400(payload_data.get("image_assets_json"), tenant_id)
    page = KnowledgePage(tenant_id=tenant_id, **payload_data)
    db.add(page)
    db.flush()
    knowledge_service.rebuild_chunks(db, page)
    audit_service.record(
        db=db,
        tenant_id=str(page.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="knowledge_page.created",
        target_type="knowledge_page",
        target_id=str(page.id),
        detail_json={"bot_profile_id": str(page.bot_profile_id)},
    )
    db.commit()
    db.refresh(page)
    return page


@router.patch("/{page_id}", response_model=KnowledgePageResponse)
def update_knowledge_page(
    page_id: str,
    payload: KnowledgePageUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> KnowledgePage:
    page = db.get(KnowledgePage, UUID(page_id))
    if not page:
        raise HTTPException(status_code=404, detail="Knowledge page not found")
    ensure_tenant_access(user, page.tenant_id)
    payload_data = payload.model_dump(exclude_unset=True)
    if "image_assets_json" in payload_data:
        payload_data["image_assets_json"] = validate_image_assets_or_400(payload_data.get("image_assets_json"), page.tenant_id)
        try:
            image_storage_service.delete_removed_image_assets(page.image_assets_json, payload_data["image_assets_json"])
        except (ImageStorageError, ImageValidationError) as exc:
            raise_image_delete_error(exc)
    for key, value in payload_data.items():
        setattr(page, key, value)
    db.flush()
    knowledge_service.rebuild_chunks(db, page)
    audit_service.record(
        db=db,
        tenant_id=str(page.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="knowledge_page.updated",
        target_type="knowledge_page",
        target_id=str(page.id),
        detail_json=payload_data,
    )
    db.commit()
    db.refresh(page)
    return page


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_page(
    page_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
) -> Response:
    page = db.get(KnowledgePage, UUID(page_id))
    if not page:
        raise HTTPException(status_code=404, detail="Knowledge page not found")
    ensure_tenant_access(user, page.tenant_id)
    try:
        image_storage_service.delete_image_assets(page.image_assets_json)
    except (ImageStorageError, ImageValidationError) as exc:
        raise_image_delete_error(exc)
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_page_id == page.id))
    audit_service.record(
        db=db,
        tenant_id=str(page.tenant_id),
        actor_type="user",
        actor_id=str(user.id),
        action="knowledge_page.deleted",
        target_type="knowledge_page",
        target_id=str(page.id),
        detail_json={"bot_profile_id": str(page.bot_profile_id)},
    )
    db.delete(page)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
