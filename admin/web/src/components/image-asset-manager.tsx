"use client";

import { ChangeEvent } from "react";

import { ImageAsset } from "@/types/api";

interface ImageAssetManagerProps {
  assets: ImageAsset[];
  disabled?: boolean;
  onUpload: (file: File) => void;
  onRemove: (asset: ImageAsset) => void;
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`;
  }
  if (sizeBytes >= 1024) {
    return `${Math.round(sizeBytes / 1024)} KB`;
  }
  return `${sizeBytes} B`;
}

export function ImageAssetManager({ assets, disabled, onUpload, onRemove }: ImageAssetManagerProps) {
  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) {
      return;
    }
    onUpload(file);
  }

  return (
    <div className="image-manager">
      <div className="image-manager-header">
        <div>
          <strong>图片回复</strong>
          <p>支持 jpg、png、webp，单张最大 5MB。图片会上传到 Backblaze B2 / S3-compatible 存储，并用于网页展示和 Telegram 自动回复。</p>
        </div>
        <label className="image-upload-button">
          上传图片
          <input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled} onChange={handleFileChange} />
        </label>
      </div>

      {assets.length ? (
        <div className="image-asset-grid">
          {assets.map((asset) => (
            <div key={asset.object_key} className="image-asset-card">
              <img src={asset.url} alt={asset.filename} />
              <div className="image-asset-body">
                <strong>{asset.filename}</strong>
                <span>{formatFileSize(asset.size_bytes)}</span>
                <span className="mono-text">{asset.object_key}</span>
              </div>
              <button type="button" className="button-danger button-inline" disabled={disabled} onClick={() => onRemove(asset)}>
                删除图片
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">暂无图片。命中这条内容时只发送文字。</p>
      )}
    </div>
  );
}
