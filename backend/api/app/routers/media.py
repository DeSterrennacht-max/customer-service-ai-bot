from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.api.app.db.session import get_db
from backend.api.app.dependencies import ensure_tenant_access, get_accessible_bot_profile, get_current_user
from backend.api.app.schemas.content import ImageAsset, ImageDeleteRequest
from backend.api.app.services.image_storage_service import ImageStorageError, ImageValidationError, ObjectImageStorageService

router = APIRouter(prefix="/admin/media", tags=["media"])
image_storage_service = ObjectImageStorageService()


def storage_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ImageValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/images", response_model=ImageAsset)
async def upload_image(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[object, Depends(get_current_user)],
    bot_profile_id: Annotated[UUID, Form()],
    resource_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    bot_profile = get_accessible_bot_profile(db, user, bot_profile_id)
    data = await file.read()
    try:
        return image_storage_service.upload_image(
            tenant_id=bot_profile.tenant_id,
            resource_type=resource_type,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
        )
    except (ImageStorageError, ImageValidationError) as exc:
        raise storage_error_to_http(exc) from exc


@router.delete("/images", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    payload: ImageDeleteRequest,
    user: Annotated[object, Depends(get_current_user)],
) -> None:
    tenant_id = image_storage_service.tenant_id_from_object_key(payload.object_key)
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image object key")
    ensure_tenant_access(user, tenant_id)
    try:
        image_storage_service.delete_image(payload.object_key)
    except (ImageStorageError, ImageValidationError) as exc:
        raise storage_error_to_http(exc) from exc
