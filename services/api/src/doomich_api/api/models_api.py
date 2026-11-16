"""Раздача моделей для устройств (например, слово активации «Думыч» в ONNX)."""

from __future__ import annotations

from doomich_common.registry import ModelKind, ModelRegistry, RegistryError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from doomich_api.api.deps import current_user
from doomich_api.config import get_settings
from doomich_api.context import UserContext

router = APIRouter(prefix="/v1/models", tags=["models"])


class DeviceModelOut(BaseModel):
    kind: str
    tenant: str
    version: str
    metrics: dict[str, float]
    params: dict


def _active(user: UserContext):
    try:
        manifest = ModelRegistry(get_settings().registry_dir).active(user.university_slug, ModelKind.WAKEWORD)
    except RegistryError:
        manifest = None
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель слова активации ещё не опубликована")
    return manifest


@router.get("/wakeword", response_model=DeviceModelOut)
async def wakeword_info(user: UserContext = Depends(current_user)):
    m = _active(user)
    return DeviceModelOut(kind=m.kind.value, tenant=m.tenant, version=m.version, metrics=m.metrics, params=m.params)


@router.get("/wakeword/file")
async def wakeword_file(user: UserContext = Depends(current_user)):
    manifest = _active(user)
    path = ModelRegistry(get_settings().registry_dir).artifact_path(manifest, "onnx")
    return FileResponse(path, media_type="application/octet-stream", filename=f"wakeword-{manifest.version}.onnx")
