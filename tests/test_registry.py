from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from app.core.registry import VoiceRegistry


class VoiceRegistryContractTests(unittest.TestCase):
    def test_startup_default_model_preset_is_runtime_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "configs" / "server.toml"
            preset_dir = root / "configs" / "model-presets"
            voice_set_dir = root / "configs" / "voice-sets"
            voices_dir = root / "runtime" / "voices"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                '[startup]\ndefault_model_preset = "from-startup"\n',
                encoding="utf-8",
            )

            registry = VoiceRegistry(
                voices_dir,
                server_config_path=config_path,
                model_presets_dir=preset_dir,
                voice_sets_dir=voice_set_dir,
            )

            self.assertEqual(registry.active_model_preset_id(), "from-startup")

    def test_pixi_tasks_do_not_encode_surface_or_preload_modes(self) -> None:
        pixi_path = Path(__file__).resolve().parents[1] / "pixi.toml"
        with pixi_path.open("rb") as file:
            pixi_config = tomllib.load(file)

        tasks = pixi_config["tasks"]
        self.assertIn("api", tasks)
        self.assertIn("admin", tasks)
        self.assertIn("serve", tasks)
        self.assertIn("test", tasks)
        self.assertIn("smoke", tasks)

        forbidden = {
            "api-preload",
            "api-admin",
            "api-admin-preload",
            "combined",
            "combined-asr",
            "webui",
            "webui-asr",
        }
        self.assertFalse(forbidden.intersection(tasks))


if __name__ == "__main__":
    unittest.main()
