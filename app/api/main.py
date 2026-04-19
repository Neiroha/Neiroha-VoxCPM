from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.health import router as health_router
from app.api.routers.openai_tts import router as openai_router
from app.api.routers.voices import router as voices_router
from app.api.routers.voxcpm_native import router as native_router
from app.core.registry import VoiceRegistry
from app.services.synthesis_service import VoxCPMRuntime


def create_api_app(runtime: VoxCPMRuntime, voice_registry: VoiceRegistry | None = None) -> FastAPI:
    app = FastAPI(
        title="VoxCPM Local Launcher",
        version="0.3.0",
        description="Decoupled FastAPI wrapper around the official VoxCPM runtime with OpenAI-compatible and native routes.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.runtime = runtime
    app.state.voice_registry = voice_registry or VoiceRegistry()

    app.include_router(health_router)
    app.include_router(openai_router)
    app.include_router(native_router)
    app.include_router(voices_router)
    return app
