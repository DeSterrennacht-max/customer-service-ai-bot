from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.api.app.services.image_storage_service import ImageStorageError, ImageValidationError, ObjectImageStorageService, normalize_image_assets


class FakeObjectStorageClient:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {"ResponseMetadata": {"HTTPStatusCode": 204}}


def object_storage_settings() -> SimpleNamespace:
    return SimpleNamespace(
        object_storage_endpoint_url="https://s3.us-west-004.backblazeb2.com",
        object_storage_access_key_id="access-key",
        object_storage_secret_access_key="secret-key",
        object_storage_bucket="media-bucket",
        object_storage_public_base_url="https://media.example.com",
        object_storage_max_image_bytes=5 * 1024 * 1024,
        r2_endpoint_url=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket=None,
        r2_public_base_url=None,
        r2_max_image_bytes=5 * 1024 * 1024,
    )


def test_upload_image_stores_object_and_returns_public_asset() -> None:
    tenant_id = uuid4()
    client = FakeObjectStorageClient()
    service = ObjectImageStorageService(settings=object_storage_settings(), client=client)

    asset = service.upload_image(
        tenant_id=tenant_id,
        resource_type="faq",
        filename="price.png",
        content_type="image/png",
        data=b"png-bytes",
    )

    assert asset["url"].startswith(f"https://media.example.com/tenants/{tenant_id}/content-images/faq/")
    assert asset["object_key"].startswith(f"tenants/{tenant_id}/content-images/faq/")
    assert asset["filename"] == "price.png"
    assert asset["content_type"] == "image/png"
    assert asset["size_bytes"] == len(b"png-bytes")
    assert client.put_calls[0]["Bucket"] == "media-bucket"
    assert client.put_calls[0]["ContentType"] == "image/png"


def test_upload_image_rejects_unsupported_type() -> None:
    service = ObjectImageStorageService(settings=object_storage_settings(), client=FakeObjectStorageClient())

    with pytest.raises(ImageValidationError):
        service.upload_image(
            tenant_id=uuid4(),
            resource_type="faq",
            filename="bad.gif",
            content_type="image/gif",
            data=b"gif-bytes",
        )


def test_delete_removed_image_assets_deletes_only_removed_objects() -> None:
    client = FakeObjectStorageClient()
    service = ObjectImageStorageService(settings=object_storage_settings(), client=client)

    service.delete_removed_image_assets(
        old_assets=[
            {"url": "https://media.example.com/a.png", "object_key": "tenants/11111111-1111-1111-1111-111111111111/content-images/faq/a.png"},
            {"url": "https://media.example.com/b.png", "object_key": "tenants/11111111-1111-1111-1111-111111111111/content-images/faq/b.png"},
        ],
        new_assets=[
            {"url": "https://media.example.com/b.png", "object_key": "tenants/11111111-1111-1111-1111-111111111111/content-images/faq/b.png"},
        ],
    )

    assert client.delete_calls == [
        {
            "Bucket": "media-bucket",
            "Key": "tenants/11111111-1111-1111-1111-111111111111/content-images/faq/a.png",
        }
    ]


def test_tenant_id_from_object_key_parses_owned_prefix() -> None:
    tenant_id = uuid4()

    parsed = ObjectImageStorageService.tenant_id_from_object_key(f"tenants/{tenant_id}/content-images/faq/image.png")

    assert parsed == tenant_id
    assert isinstance(parsed, UUID)
    assert ObjectImageStorageService.tenant_id_from_object_key("bad/key") is None


def test_missing_object_storage_config_uses_generic_error_message() -> None:
    settings = SimpleNamespace(
        object_storage_endpoint_url=None,
        object_storage_access_key_id=None,
        object_storage_secret_access_key=None,
        object_storage_bucket=None,
        object_storage_public_base_url=None,
        object_storage_max_image_bytes=5 * 1024 * 1024,
        r2_endpoint_url=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket=None,
        r2_public_base_url=None,
        r2_max_image_bytes=5 * 1024 * 1024,
    )
    service = ObjectImageStorageService(settings=settings, client=FakeObjectStorageClient())

    with pytest.raises(ImageStorageError) as exc_info:
        service.upload_image(
            tenant_id=uuid4(),
            resource_type="faq",
            filename="price.png",
            content_type="image/png",
            data=b"png-bytes",
        )

    assert "Object image storage is not configured" in str(exc_info.value)
    assert "R2" not in str(exc_info.value)


def test_normalize_image_assets_dedupes_invalid_items() -> None:
    assets = normalize_image_assets(
        [
            {"url": "https://media.example.com/a.png", "object_key": "key-a", "filename": "a.png", "content_type": "image/png", "size_bytes": 12},
            {"url": "https://media.example.com/a.png", "object_key": "key-a", "filename": "a.png", "content_type": "image/png", "size_bytes": 12},
            {"url": "", "object_key": "missing-url"},
            "invalid",
        ]
    )

    assert assets == [
        {
            "url": "https://media.example.com/a.png",
            "object_key": "key-a",
            "filename": "a.png",
            "content_type": "image/png",
            "size_bytes": 12,
        }
    ]
