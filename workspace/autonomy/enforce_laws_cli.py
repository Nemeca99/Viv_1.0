"""Standalone 8-law lever checker for the live OpenCode tool path.

Loads security_core.dll and runs enforce_morality (the 8-law enforcement) on one
tool call. Fail-closed: any load/parse error => denied. Exit 0 = allowed, 1 = denied.

This is the bridge between the live OpenCode tool names and the security core's
legacy vocabulary. It does NOT deny on its own; it only reports what the 8 laws say,
so the caller decides the policy.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace\aios_rebuild")
LIBRARY = WORKSPACE / "local_security_core" / "target" / "debug" / "security_core.dll"

# OpenCode/live tool name -> security-core vocabulary (governor.rs is_fs_tool / is_mutating_tool).
TOOL_NAME_MAP = {
    "write": "write_file",
    "localcoder_write_exact": "write_file",
    "localcoder_add_python": "write_file",
    "localcoder_memory_append": "write_file",
    "edit": "patch_file",
    "patch": "patch_file",
    "localcoder_patch": "patch_file",
    "apply_patch": "apply_diff",
    "delete": "delete_file",
    "remove": "delete_file",
    "rename": "rename_file",
    "move": "move_file",
    "copy": "write_file",
    "mkdir": "fs_write",
    "rmdir": "fs_delete",
    "touch": "fs_write",
    "shell": "shell",
    "bash": "shell",
    "terminal": "shell",
    "read": "read_file",
    "localcoder_memory_read": "read_file",
    "glob": "list_dir",
    "grep": "read_file",
}


def load_rust():
    if not LIBRARY.is_file():
        raise RuntimeError("security_core.dll not built")
    loader = importlib.machinery.ExtensionFileLoader("security_core", str(LIBRARY))
    spec = importlib.util.spec_from_file_location("security_core", LIBRARY, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def check(tool_name, params_json, s_n=1.0, forensic_buffer="", raw_input=""):
    mapped = TOOL_NAME_MAP.get(tool_name, tool_name)
    try:
        rust = load_rust()
        verdict = dict(rust.enforce_morality(mapped, params_json, float(s_n), forensic_buffer, raw_input))
    except Exception as error:  # fail-closed
        verdict = {
            "allowed": False,
            "reason": "law_enforcement_unavailable:%s" % type(error).__name__,
            "law": "bridge",
        }
    return {"tool": tool_name, "mapped": mapped, **verdict}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-name", required=True)
    parser.add_argument("--params-json", default="{}")
    parser.add_argument("--s-n", type=float, default=1.0)
    parser.add_argument("--forensic-buffer", default="")
    parser.add_argument("--raw-input", default="")
    args = parser.parse_args()
    verdict = check(args.tool_name, args.params_json, args.s_n, args.forensic_buffer, args.raw_input)
    print(json.dumps(verdict))
    sys.exit(0 if verdict.get("allowed") else 1)


if __name__ == "__main__":
    main()
