"""
Autonomous Work System for AIOS Viv
Maintains continuous operation with task queue, state persistence, and recovery.
"""

import json
from datetime import datetime
from pathlib import Path


class AutonomousWorkSystem:
    """Continuous work system that persists state and recovers from interruptions."""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent / "autonomy"
        self.state_file = self.base_dir / "work_state.json"
        self.queue_file = self.base_dir / "task_queue.json"
        self.log_file = self.base_dir / "work_log.md"
        
        # Initialize state if not exists
        if not self.state_file.exists():
            import json as j
            with open(self.state_file, 'w') as f:
                j.dump({"start_time": datetime.now().isoformat()}, f)
            
            with open(self.queue_file, 'w') as f:
                j.dump({"pending": [], "in_progress": [], "completed": []}, f)
    
    def log_action(self, action_type, description):
        """Append timestamped entry to work log."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(self.log_file, 'a') as f:
            f.write(f"\n### {ts} ###\n{action_type}: {description}\n")
    
    def add_task(self, task_name):
        """Add task to pending queue."""
        import json as j
        
        with open(self.queue_file, 'r') as f:
            queue = j.load(f)
        
        queue["pending"].append({
            "name": task_name,
            "added_at": datetime.now().isoformat(),
            "status": "pending"
        })
        
        with open(self.queue_file, 'w') as f:
            j.dump(queue, f)
        
        self.log_action("TASK_ADDED", f"Added: {task_name}")


def main():
    """Initialize and run autonomous work system."""
    system = AutonomousWorkSystem()
    
    # Define initial tasks
    tasks = [
        "Verify Python syntax on 1584 files",
        "Run regression test suite (458 tests)", 
        "Check core directories exist",
        "Verify source manifest hashes"
    ]
    
    for task in tasks:
        system.add_task(task)
    
    print(f"Autonomous Work System ready at {datetime.now()}")


if __name__ == "__main__":
    main()
