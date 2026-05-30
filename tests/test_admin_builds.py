from __future__ import annotations

import inspect
import unittest

from app.admin.voxcpm_admin import TEXT, create_admin_blocks


class AdminContractTests(unittest.TestCase):
    def test_required_tab_labels_exist(self) -> None:
        self.assertEqual(TEXT["en"]["home"], "Status")
        self.assertEqual(TEXT["en"]["model_presets"], "Model Presets")
        self.assertEqual(TEXT["en"]["voice_sets"], "Voice Sets")
        self.assertEqual(TEXT["en"]["try"], "Synthesis Test")
        self.assertEqual(TEXT["en"]["download"], "Downloads")
        self.assertEqual(TEXT["en"]["logs"], "Runtime Logs")
        self.assertEqual(TEXT["en"]["settings"], "Settings")

    def test_tab_order_matches_backend_contract(self) -> None:
        source = inspect.getsource(create_admin_blocks)
        keys = [
            'text["home"]',
            'text["model_presets"]',
            'text["voice_sets"]',
            'text["try"]',
            'text["download"]',
            'text["logs"]',
            'text["settings"]',
        ]
        positions = [source.index(f"with gr.Tab({key})") for key in keys]
        self.assertEqual(positions, sorted(positions))

    def test_admin_exposes_smoke_and_restart_operations(self) -> None:
        source = inspect.getsource(create_admin_blocks)

        self.assertIn("def run_smoke_test", source)
        self.assertIn("def restart_plan", source)
        self.assertIn('label="Smoke output"', source)
        self.assertIn('label="Restart plan"', source)


if __name__ == "__main__":
    unittest.main()
