import subprocess
import sys
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent


class ChatVivBodyGateTests(unittest.TestCase):
    def test_import_does_not_load_neural_runtime_before_body_authorization(self):
        code = (
            f"import sys; sys.path.insert(0, {str(WORKSPACE_ROOT)!r}); "
            "import builtins, types; "
            "main_core = types.ModuleType('main_core'); main_core.__path__ = []; "
            "main_module = types.ModuleType('main_core.main_core'); "
            "main_module.kernel = types.SimpleNamespace(get_mind_runtime_gate="
            "lambda **kwargs: {'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME', "
            "'authority': 'deterministic_aios_body_rust', 'reasons': ['test_hold']}); "
            "sys.modules['main_core'] = main_core; "
            "sys.modules['main_core.main_core'] = main_module; "
            "import chat_viv; "
            "assert 'torch' not in sys.modules; "
            "assert 'autonomy.speak_unified_viv' not in sys.modules; "
            "chat_viv.DualContextMemory = lambda: types.SimpleNamespace(" 
            "chat_history=[], ltm_raw=[], stm={}); "
            "builtins.input = lambda _: '/exit'; chat_viv.interactive_chat(); "
            "assert 'torch' not in sys.modules; "
            "assert 'autonomy.speak_unified_viv' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
