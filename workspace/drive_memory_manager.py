import os
import sys
import json
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DRIVE_MEMORIES = {
    "C:": "C:\\_drive_index\\drive_memory.jsonl",
    "D:": "D:\\_drive_index\\drive_memory.jsonl",
    "E:": "E:\\_drive_index\\drive_memory.jsonl",
    "F:": "F:\\_drive_index\\drive_memory.jsonl",
    "L:": "L:\\_drive_index\\drive_memory.jsonl", # Sovereign Queen Memory
}

class DriveMemoryManager:
    def __init__(self):
        for drive, path in DRIVE_MEMORIES.items():
            dir_path = os.path.dirname(path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    pass

    def record_drive_memory(self, target_drive: str, actor: str, statement: str, action: str):
        """
        Appends a local memory entry strictly to the target drive's isolated memory log.
        """
        d_clean = target_drive[:2].upper()
        if d_clean not in DRIVE_MEMORIES:
            raise ValueError(f"Unknown drive memory target: {d_clean}")
            
        memory_path = DRIVE_MEMORIES[d_clean]
        entry = {
            "timestamp": datetime.now().isoformat(),
            "drive": d_clean,
            "actor": actor,
            "statement": statement,
            "action": action
        }
        
        with open(memory_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
            
        print(f"[MEMORY LOGGED] -> {d_clean} Memory ({actor}): '{action}'")

    def queen_read_drive_memory(self, source_drive: str, limit: int = 5) -> list:
        """
        The Queen on L: reads the memory of any outer drive (READ-ONLY).
        """
        d_clean = source_drive[:2].upper()
        if d_clean not in DRIVE_MEMORIES:
            raise ValueError(f"Unknown drive memory source: {d_clean}")
            
        memory_path = DRIVE_MEMORIES[d_clean]
        memories = []
        if os.path.exists(memory_path):
            with open(memory_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    if line.strip():
                        try:
                            memories.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            pass
        return memories

if __name__ == "__main__":
    print("=== Testing Per-Drive Isolated Memory Architecture ===")
    manager = DriveMemoryManager()
    
    # 1. Record Sovereign Queen Memory on L:
    manager.record_drive_memory("L:", actor="RustQueen", statement="Rules Core recompiled in release mode.", action="RULE_RECOMPILE")
    
    # 2. Record C: Drive Local Memory
    manager.record_drive_memory("C:", actor="C_Domain_Specialist", statement="OS system directory scan completed.", action="SYS_SCAN")

    # 3. Record D: Drive Local Memory
    manager.record_drive_memory("D:", actor="D_Domain_Specialist", statement="Pytest sandbox run passed 100%.", action="TEST_RUN")

    # 4. Queen on L: Reads C: and D: Memory (READ-ONLY)
    print("\n--- Queen Read-Only Inspection of C: Drive Memory ---")
    c_mem = manager.queen_read_drive_memory("C:")
    print(json.dumps(c_mem, indent=2))

    print("\n--- Queen Read-Only Inspection of D: Drive Memory ---")
    d_mem = manager.queen_read_drive_memory("D:")
    print(json.dumps(d_mem, indent=2))
