from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np

from app.api.common import audio_response
from app.api.main import create_api_app
from app.core.registry import VoiceRegistry
from app.services.synthesis_service import VoxCPMRuntime


class FakeRuntime(VoxCPMRuntime):
    model_id = "models/OpenBMB__VoxCPM2"
    requested_device = "cpu"
    status_device = "cpu"
    voxcpm_model = None
    asr_enabled = False
    asr_model = None
    asr_model_source = "models/iic__SenseVoiceSmall"
    load_denoiser = False
    launch_info: dict[str, object] = {}

    def __init__(self) -> None:
        self.synthesis_requests = []

    def synthesize(self, request):
        self.synthesis_requests.append(request)
        return 48000, np.zeros(480, dtype="float32")


def make_registry(root: Path, *, api_key: str = "") -> VoiceRegistry:
    config_root = root / "configs"
    preset_dir = config_root / "model-presets"
    voice_set_dir = config_root / "voice-sets"
    voices_dir = root / "runtime" / "voices"
    preset_dir.mkdir(parents=True)
    voice_set_dir.mkdir(parents=True)
    voices_dir.mkdir(parents=True)
    (config_root / "server.toml").write_text(
        "\n".join(
            [
                "[api]",
                'host = "127.0.0.1"',
                "port = 8000",
                "",
                "[admin]",
                'host = "127.0.0.1"',
                "port = 7860",
                "",
                "[startup]",
                'surface = "both"',
                "preload_model = false",
                'default_model_preset = "voxcpm2-default"',
                "",
                "[security]",
                f'api_key = "{api_key}"',
                "",
                "[runtime]",
                'active_voice_set = "default"',
                'default_voice = "voxcpm2-design"',
            ]
        ),
        encoding="utf-8",
    )
    (preset_dir / "default.toml").write_text(
        "\n".join(
            [
                "schema_version = 1",
                'id = "voxcpm2-default"',
                'name = "VoxCPM2 Default"',
                'engine = "voxcpm2"',
                "",
                "[voxcpm2]",
                'model_id = "models/OpenBMB__VoxCPM2"',
                'device = "cpu"',
            ]
        ),
        encoding="utf-8",
    )
    (voice_set_dir / "default.toml").write_text(
        'schema_version = 1\nid = "default"\nname = "Default"\nvoices = []\n',
        encoding="utf-8",
    )
    return VoiceRegistry(
        voices_dir,
        server_config_path=config_root / "server.toml",
        model_presets_dir=preset_dir,
        voice_sets_dir=voice_set_dir,
    )


class APIContractTests(unittest.TestCase):
    def test_openai_and_native_contract_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(Path(tmp))
            app = create_api_app(FakeRuntime(), registry)
            client = TestClient(app)

            self.assertEqual(client.get("/health").json()["status"], "ok")
            self.assertEqual(client.get("/v1/models").json()["data"][0]["id"], "default")
            self.assertIn("data", client.get("/v1/audio/voices").json())
            routes = client.get("/api/voxcpm/capabilities").json()["routes"]
            self.assertEqual(routes["native_speech"], "/api/voxcpm/tts")

    def test_flutter_voxcpm_native_adapter_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(Path(tmp))
            runtime = FakeRuntime()
            app = create_api_app(runtime, registry)
            client = TestClient(app)

            response = client.post(
                "/api/voxcpm/tts",
                json={"model": "default", "text": "hello", "mode": "design", "response_format": "wav"},
            )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["X-Neiroha-Backend"], "voxcpm")
            self.assertEqual(runtime.synthesis_requests[-1].mode, "design")
            self.assertEqual(runtime.synthesis_requests[-1].response_format, "wav")

            upload_response = client.post(
                "/api/voxcpm/tts/upload",
                data={"model": "default", "text": "hello", "mode": "clone", "response_format": "wav"},
                files={"reference_audio": ("ref.wav", b"RIFF", "audio/wav")},
            )

            self.assertEqual(upload_response.status_code, 200, upload_response.text)
            self.assertEqual(runtime.synthesis_requests[-1].mode, "clone")
            self.assertTrue(runtime.synthesis_requests[-1].reference_audio_path)

            legacy_response = client.post(
                "/voxcpm/speech",
                json={"model": "voxcpm2", "text": "hello", "mode": "design"},
            )

            self.assertEqual(legacy_response.status_code, 200, legacy_response.text)

    def test_error_shape_for_unsupported_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(Path(tmp))
            app = create_api_app(FakeRuntime(), registry)
            client = TestClient(app)

            response = client.post(
                "/v1/audio/speech",
                json={"model": "default", "input": "hello", "response_format": "mp3"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "unsupported_format")

    def test_configured_api_key_protects_non_public_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = make_registry(Path(tmp), api_key="secret")
            app = create_api_app(FakeRuntime(), registry)
            client = TestClient(app)

            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/v1/models").status_code, 401)
            self.assertEqual(client.get("/v1/models", headers={"X-API-Key": "secret"}).status_code, 200)

    def test_audio_headers_are_safe_for_non_ascii_voice_ids(self) -> None:
        response = audio_response(
            sample_rate=48000,
            wav=np.zeros(480, dtype="float32"),
            model_id="模型",
            model_preset_id="默认",
            voice_id="中文音色",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["X-Neiroha-Voice"].startswith("voice_"))


if __name__ == "__main__":
    unittest.main()
