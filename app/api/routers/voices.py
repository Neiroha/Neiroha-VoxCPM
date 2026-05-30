from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.common import http_error_detail
from app.api.dependencies import get_runtime, get_voice_registry
from app.core.registry import VoiceRegistry
from app.core.schemas import VoiceProfileCreateRequest
from app.core.utils import dump_model
from app.services.synthesis_service import VoxCPMRuntime

router = APIRouter(tags=["voices"])


@router.get("/api/voxcpm/voices", summary="List registered local voice profiles")
@router.get("/voxcpm/voices", include_in_schema=False)
def list_registered_voices(
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    voices = [dump_model(profile) for profile in registry.list_profiles()]
    return {"object": "list", "data": voices}


@router.post("/api/voxcpm/voices", summary="Create or update a local voice profile")
@router.post("/voxcpm/voices", include_in_schema=False)
def register_voice(
    payload: VoiceProfileCreateRequest,
    registry: VoiceRegistry = Depends(get_voice_registry),
    runtime: VoxCPMRuntime = Depends(get_runtime),
):
    try:
        voice, created = registry.save_profile(payload, default_model=registry.active_voice_set_id())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=http_error_detail("invalid_reference_audio", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_error_detail("invalid_request", str(exc))) from exc

    return JSONResponse(
        content={"created": created, "voice": dump_model(voice)},
        status_code=201 if created else 200,
    )


@router.get("/api/voxcpm/voices/{voice_id}", summary="Fetch one local voice profile")
@router.get("/voxcpm/voices/{voice_id}", include_in_schema=False)
def get_voice(
    voice_id: str,
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    try:
        voice = registry.get_profile(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=http_error_detail("voice_not_found", str(exc))) from exc
    return dump_model(voice)


@router.delete("/api/voxcpm/voices/{voice_id}", summary="Delete a local voice profile")
@router.delete("/voxcpm/voices/{voice_id}", include_in_schema=False)
def delete_voice(
    voice_id: str,
    registry: VoiceRegistry = Depends(get_voice_registry),
) -> dict[str, object]:
    try:
        registry.delete_profile(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=http_error_detail("voice_not_found", str(exc))) from exc
    return {"deleted": True, "id": voice_id}
