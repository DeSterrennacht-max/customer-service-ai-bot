from __future__ import annotations

import re
import uuid
from pathlib import PurePath
from typing import Any
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from backend.api.app.core.config import Settings, get_settings


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class ImageStorageError(RuntimeError):
    pass


class ImageValidationError(ValueError):
    pass


def normalize_image_assets(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    assets: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for item in value:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        object_key = str(item.get("object_key") or "").strip()
        url = str(item.get("url") or "").strip()
        if not object_key or not url or object_key in seen_keys:
            continue
        seen_keys.add(object_key)
        assets.append(
            {
                "url": url,
                "object_key": object_key,
                "filename": str(item.get("filename") or "image").strip() or "image",
                "content_type": str(item.get("content_type") or "application/octet-stream").strip(),
                "size_bytes": int(item.get("size_bytes") or 0),
            }
        )
    return assets


class ObjectImageStorageService:
    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        self._ensure_configured()
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._config_value("object_storage_endpoint_url", "r2_endpoint_url"),
                aws_access_key_id=self._config_value("object_storage_access_key_id", "r2_access_key_id"),
                aws_secret_access_key=self._config_value("object_storage_secret_access_key", "r2_secret_access_key"),
                region_name="auto",
            )
        return self._client

    def upload_image(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        filename: str | None,
        content_type: str | None,
        data: bytes,
    ) -> dict[str, object]:
        self._ensure_configured()
        resource_type = self._validate_resource_type(resource_type)
        content_type = self._validate_image(filename, content_type, data)
        safe_filename = self._safe_filename(filename)
        extension = ALLOWED_IMAGE_TYPES[content_type]
        object_key = f"tenants/{tenant_id}/content-images/{resource_type}/{uuid.uuid4().hex}{extension}"

        try:
            self.client.put_object(
                Bucket=self._config_value("object_storage_bucket", "r2_bucket"),
                Key=object_key,
                Body=data,
                ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
            )
        except (BotoCoreError, ClientError) as exc:
            raise ImageStorageError("Image upload failed") from exc

        return {
            "url": self.public_url(object_key),
            "object_key": object_key,
            "filename": safe_filename,
            "content_type": content_type,
            "size_bytes": len(data),
        }

    def delete_image(self, object_key: str) -> None:
        self._ensure_configured()
        object_key = object_key.strip()
        if not object_key:
            raise ImageValidationError("Image object key is required")
        try:
            self.client.delete_object(Bucket=self._config_value("object_storage_bucket", "r2_bucket"), Key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise ImageStorageError("Image delete failed") from exc

    def delete_image_assets(self, assets: object) -> None:
        for asset in normalize_image_assets(assets):
            self.delete_image(str(asset["object_key"]))

    def delete_removed_image_assets(self, old_assets: object, new_assets: object) -> None:
        next_keys = {str(asset["object_key"]) for asset in normalize_image_assets(new_assets)}
        for asset in normalize_image_assets(old_assets):
            if str(asset["object_key"]) not in next_keys:
                self.delete_image(str(asset["object_key"]))

    def validate_assets_owned_by_tenant(self, assets: object, tenant_id: uuid.UUID) -> list[dict[str, object]]:
        normalized_assets = normalize_image_assets(assets)
        for asset in normalized_assets:
            asset_tenant_id = self.tenant_id_from_object_key(str(asset["object_key"]))
            if asset_tenant_id != tenant_id:
                raise ImageValidationError("Image asset does not belong to this tenant")
        return normalized_assets

    def public_url(self, object_key: str) -> str:
        public_base_url = str(self._config_value("object_storage_public_base_url", "r2_public_base_url")).rstrip("/")
        return f"{public_base_url}/{quote(object_key, safe='/')}"

    @staticmethod
    def tenant_id_from_object_key(object_key: str) -> uuid.UUID | None:
        parts = object_key.split("/")
        if len(parts) < 2 or parts[0] != "tenants":
            return None
        try:
            return uuid.UUID(parts[1])
        except ValueError:
            return None

    def _ensure_configured(self) -> None:
        missing = [
            name
            for name, value in {
                "APP_OBJECT_STORAGE_ENDPOINT_URL": self._config_value("object_storage_endpoint_url", "r2_endpoint_url"),
                "APP_OBJECT_STORAGE_ACCESS_KEY_ID": self._config_value("object_storage_access_key_id", "r2_access_key_id"),
                "APP_OBJECT_STORAGE_SECRET_ACCESS_KEY": self._config_value("object_storage_secret_access_key", "r2_secret_access_key"),
                "APP_OBJECT_STORAGE_BUCKET": self._config_value("object_storage_bucket", "r2_bucket"),
                "APP_OBJECT_STORAGE_PUBLIC_BASE_URL": self._config_value("object_storage_public_base_url", "r2_public_base_url"),
            }.items()
            if not value
        ]
        if missing:
            raise ImageStorageError(f"Object image storage is not configured: {', '.join(missing)}")

    @staticmethod
    def _validate_resource_type(resource_type: str) -> str:
        if resource_type not in {"faq", "knowledge_page"}:
            raise ImageValidationError("Unsupported image resource type")
        return resource_type

    def _validate_image(self, filename: str | None, content_type: str | None, data: bytes) -> str:
        if not data:
            raise ImageValidationError("Image file is empty")
        if len(data) > self._max_image_bytes():
            raise ImageValidationError("Image file is too large")

        normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
        if normalized_type not in ALLOWED_IMAGE_TYPES:
            raise ImageValidationError("Only jpg, png, and webp images are supported")

        suffix = PurePath(filename or "").suffix.lower()
        allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
        if suffix and suffix not in allowed_suffixes:
            raise ImageValidationError("Only jpg, png, and webp images are supported")
        return normalized_type

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        basename = PurePath(filename or "image").name
        basename = re.sub(r"[\r\n\t]+", " ", basename).strip()
        return basename[:180] or "image"

    def _config_value(self, preferred_name: str, fallback_name: str) -> object:
        return getattr(self.settings, preferred_name, None) or getattr(self.settings, fallback_name, None)

    def _max_image_bytes(self) -> int:
        return int(self._config_value("object_storage_max_image_bytes", "r2_max_image_bytes") or 5 * 1024 * 1024)
