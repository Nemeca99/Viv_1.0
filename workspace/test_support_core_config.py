import sys
import unittest
from pathlib import Path
from unittest.mock import patch

AIOS_REBUILD = Path(__file__).resolve().parent / "aios_rebuild"
if str(AIOS_REBUILD) not in sys.path:
    sys.path.insert(0, str(AIOS_REBUILD))

from support_core.core.config import AIOSConfig, DEFAULT_CONFIG_FILE, aios_config


class SupportCoreConfigPathTests(unittest.TestCase):
    def test_default_config_is_anchored_to_active_aios_root(self):
        expected = AIOS_REBUILD / "data_core" / "config" / "aios_config.json"

        self.assertEqual(DEFAULT_CONFIG_FILE, expected)
        self.assertEqual(aios_config.config_file, expected)
        self.assertEqual(aios_config.get("AIOS_ROOT"), str(AIOS_REBUILD))
        self.assertTrue(Path(aios_config.get("PYTHON_ENV_PATH")).is_dir())

    def test_explicit_config_path_remains_compatible(self):
        configured = Path("custom") / "aios_config.json"

        with patch.object(AIOSConfig, "_load_config"), patch.object(AIOSConfig, "_validate_config"):
            self.assertEqual(AIOSConfig(configured).config_file, configured)


if __name__ == "__main__":
    unittest.main()
