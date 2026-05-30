from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.common import error_code_for_status, error_response
from app.api.routers.health import router as health_router
from app.api.routers.openai_tts import router as openai_router
from app.api.routers.voices import router as voices_router
from app.api.routers.voxcpm_native import router as native_router
from app.core.registry import VoiceRegistry
from app.services.synthesis_service import VoxCPMRuntime


def _message_from_detail(detail: object) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "Request failed.")
    return str(detail or "Request failed.")


def _code_from_detail(detail: object, status_code: int) -> str:
    if isinstance(detail, dict):
        code = detail.get("code")
        if code:
            return str(code)
    return error_code_for_status(status_code)


def _details_from_detail(detail: object) -> dict[str, object]:
    if isinstance(detail, dict):
        details = detail.get("details")
        return details if isinstance(details, dict) else {}
    return {}


def _configured_api_key(voice_registry: VoiceRegistry) -> str:
    security = voice_registry.server_config().get("security", {})
    if not isinstance(security, dict):
        return ""
    return str(security.get("api_key") or "").strip()


def _request_api_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("x-api-key", "").strip()


def create_api_app(
    runtime: VoxCPMRuntime,
    voice_registry: VoiceRegistry | None = None,
    launch_info: dict[str, object] | None = None,
) -> FastAPI:
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
    app.state.launch_info = launch_info or {}
    runtime.launch_info = app.state.launch_info

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        expected_api_key = _configured_api_key(app.state.voice_registry)
        public_paths = {"/", "/health", "/api/health"}
        if expected_api_key and request.url.path not in public_paths:
            if _request_api_key(request) != expected_api_key:
                return error_response(
                    "auth_required",
                    "A valid API key is required.",
                    status_code=401,
                    error_type="auth_error",
                )
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def contract_http_exception_handler(request: Request, exc: StarletteHTTPException):
        return error_response(
            _code_from_detail(exc.detail, exc.status_code),
            _message_from_detail(exc.detail),
            status_code=exc.status_code,
            details=_details_from_detail(exc.detail),
        )

    app.include_router(health_router)
    app.include_router(openai_router)
    app.include_router(native_router)
    app.include_router(voices_router)
    return app
