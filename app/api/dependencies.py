from __future__ import annotations

from fastapi import Request

from app.core.registry import VoiceRegistry
from app.services.synthesis_service import VoxCPMRuntime


def get_runtime(request: Request) -> VoxCPMRuntime:
    return request.app.state.runtime


def get_voice_registry(request: Request) -> VoiceRegistry:
    return request.app.state.voice_registry
