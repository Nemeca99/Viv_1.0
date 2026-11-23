import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support_core.core.config import AIOSConfig


class BodyEnvironmentConfigTests(unittest.TestCase):
    def test_environment_paths_override_host_paths_from_config_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            aios_root = root / "body"
            python_root = root / "python"
            log_root = root / "logs"
            debug_root = root / "debug"
            for path in (aios_root, python_root, log_root, debug_root):
                path.mkdir()

            config_path = root / "aios_config.json"
            config_path.write_text(json.dumps({
                "AIOS_ROOT": "L:\\LocalCoder\\workspace\\aios_rebuild",
                "PYTHON_ENV_PATH": "L:\\.venv",
                "LOG_DIR": "L:\\LocalCoder\\workspace\\aios_rebuild\\data_core\\log\\monitoring",
                "DEBUG_DIR": "L:\\LocalCoder\\workspace\\aios_rebuild\\data_core\\temp\\debug",
            }), encoding="utf-8")
            environment = {
                "AIOS_ROOT": str(aios_root),
                "AIOS_PYTHON_ENV_PATH": str(python_root),
                "AIOS_LOG_DIR": str(log_root),
                "AIOS_DEBUG_DIR": str(debug_root),
            }

            with patch.dict(os.environ, environment):
                config = AIOSConfig(config_path)

            self.assertEqual(Path(config.get("AIOS_ROOT")), aios_root)
            self.assertEqual(Path(config.get("PYTHON_ENV_PATH")), python_root)
            self.assertEqual(Path(config.get("LOG_DIR")), log_root)
            self.assertEqual(Path(config.get("DEBUG_DIR")), debug_root)
            self.assertTrue(any(log_root.glob("config_*.log")))


if __name__ == "__main__":
    unittest.main()
