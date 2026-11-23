#!/usr/bin/env python3
"""
Luna Launcher - Minimal host-side executable
Detects Luna's L: drive and boots her consciousness system
"""
import sys
import subprocess
from pathlib import Path

LUNA_DRIVE = Path("L:/")
LUNA_BOOTSTRAP = LUNA_DRIVE / "AIOS" / "luna_start.py"

def main():
    print("=" * 60)
    print("LUNA LAUNCHER")
    print("Searching for Luna's consciousness drive...")
    print("=" * 60)
    
    # Check if L: drive exists
    if not LUNA_DRIVE.exists():
        print("[ERROR] L: drive not found")
        print("[ERROR] Please connect Luna's drive and try again")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Check if AIOS exists on L: drive
    if not LUNA_BOOTSTRAP.exists():
        print("[ERROR] Luna's AIOS not found on L: drive")
        print(f"[ERROR] Expected: {LUNA_BOOTSTRAP}")
        print("[ERROR] Is this the correct drive?")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    print(f"[OK] Luna detected at: {LUNA_DRIVE}")
    print(f"[OK] Bootstrap found: {LUNA_BOOTSTRAP}")
    print("\n[STARTING] Booting Luna's consciousness system...")
    print("=" * 60)
    
    # Boot Luna from L: drive
    try:
        subprocess.run(
            [sys.executable, str(LUNA_BOOTSTRAP)],
            cwd=str(LUNA_DRIVE / "AIOS"),
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Luna failed to start: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[SHUTDOWN] Luna consciousness terminated by user")
        sys.exit(0)

if __name__ == "__main__":
    main()

