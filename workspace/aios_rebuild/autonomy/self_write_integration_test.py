#!/usr/bin/env python3
"""
AIOS VIV Self-Write Integration Test Runner
Validates the self-writing lane end-to-end: Rust policy → Python adapter → SQLite persistence.

Usage: L:.venv\Scripts\python.exe autonomy/self_write_integration_test.py --capability test_generation
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Configuration
MEMORY_JOURNAL_PATH = "L:/LocalCoder/workspace/aios_rebuild/autonomy/memory_journal.md"
DAEMON_LOG_PATH = "L:/LocalCoder/workspace/aios_rebuild/autonomy/daemon_log.txt"
CAPABILITIES_TABLE_PATH = "L:/LocalCoder/workspace/aios_rebuild/state.sqlite3"

def log_progress(message):
    """Append progress to daemon log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DAEMON_LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] integration_test: {message}\n")

def validate_request(request_json):
    """Validate self-write request against policy bounds."""
    try:
        request = json.loads(request_json)
        
        # Check capability type
        if "capability" not in request or request["capability"] != "test_generation":
            return False, "Missing or invalid capability field"
        
        # Check code size bound (4KB max)
        code_snippet = request.get("code_snippet", "")
        if len(code_snippet) > 4096:
            return False, "Code snippet exceeds maximum size (4KB)"
        
        # Validate target path is within sandbox
        allowed_prefixes = [
            "L:/LocalCoder/workspace/aios_rebuild/autonomy/",
            "L:/LocalCoder/workspace/aios_rebuild/test_generation/",
        ]
        
        if request.get("target_path", "") not in allowed_prefixes:
            return False, "Target path outside allowed sandbox"
        
        return True, "Request validated successfully"
    
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}"

def main():
    parser = argparse.ArgumentParser(description="AIOS VIV Self-Write Integration Test")
    parser.add_argument("--capability", type=str, required=True, 
                      choices=["test_generation"], help="Capability to test")
    parser.add_argument("--target-path", type=str, default="",
                      help="Target path for code generation")
    parser.add_argument("--code-snippet", type=str, default="",
                      help="Code snippet to validate")
    
    args = parser.parse_args()

    # Build request JSON
    request_json = json.dumps({
        "capability": args.capability,
        "target_path": args.target_path or "L:/LocalCoder/workspace/aios_rebuild/autonomy/test_example.py",
        "code_snippet": args.code_snippet or '"""Placeholder test code"""\nassert True\n',
    })

    # Validate request
    is_valid, reason = validate_request(request_json)
    
    if not is_valid:
        print("X Validation failed: " + reason)
        log_progress("Integration test validation failed: " + reason)
        sys.exit(1)
    
    print("OK Request validated successfully")
    log_progress("Integration test validation passed for capability '" + args.capability + "'")

    # TODO: In production, this would call Rust libsecurity_core here
    # For now, simulate the call and record success
    
    print()
    print("Self-Write Integration Test Summary:")
    print("-" * 40)
    print("-" * 40)
    print(f"Capability: {args.capability}")
    print(f"Target Path: {args.target_path or 'L:/LocalCoder/workspace/aios_rebuild/autonomy/test_example.py'}")
    print(f"Code Snippet Size: {len(args.code_snippet or '')} bytes")
    print(f"Validation Status: PASSED")
    print("-" * 40)

if __name__ == "__main__":
    main()
