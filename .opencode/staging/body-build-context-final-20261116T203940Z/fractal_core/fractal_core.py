from typing import Dict, List, Any, Optional, Set
import uuid
import time
import json
import os
from datetime import datetime

class FractalCore:
    def __init__(self):
        self.task_graph: Dict[str, Dict[str, Any]] = {}
        self.task_status: Dict[str, Dict[str, Any]] = {}
        self.health_status: Dict[str, Any] = {
            "last_health_check": None,
            "status": "healthy",
            "error": None
        }
        self.task_id_counter = 0
        self.lock = None  # Placeholder for future synchronization

    def generate_task_id(self) -> str:
        self.task_id_counter += 1
        return f"TASK_{self.task_id_counter}"

    def create_task(self, task_id: str, name: str, description: str, dependencies: List[str] = None, parent_id: str = None) -> Dict[str, Any]:
        if dependencies is None:
            dependencies = []
        if parent_id is None:
            parent_id = ""

        task = {
            "id": task_id,
            "name": name,
            "description": description,
            "dependencies": dependencies,
            "parent_id": parent_id,
            "children": [],
            "status": "pending",
            "start_time": None,
            "end_time": None,
            "result": None
        }

        self.task_graph[task_id] = task
        self.task_status[task_id] = {
            "status": "pending",
            "progress": 0,
            "error": None
        }

        if parent_id:
            self.task_graph[parent_id]["children"].append(task_id)

        return task

    def update_task_status(self, task_id: str, status: str, progress: float = 0, error: Optional[str] = None, result: Optional[Any] = None) -> bool:
        if task_id not in self.task_graph:
            return False

        task = self.task_graph[task_id]
        task["status"] = status
        task["progress"] = progress
        task["end_time"] = datetime.now().isoformat()
        task["result"] = result
        task["error"] = error

        self.task_status[task_id] = {
            "status": status,
            "progress": progress,
            "error": error
        }

        return True

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        return self.task_status.get(task, {"status": "not_found"})

    def get_task_graph(self) -> Dict[str, Dict[str, Any]]:
        return self.task_graph

    def get_health_status(self) -> Dict[str, Any]:
        self.health_status["last_health_check"] = datetime.now().isoformat()
        return self.health_status

    def decompose_task(self, task_id: str, decomposition_strategy: str = "recursive") -> bool:
        if task_id not in self.task_graph:
            return False

        task = self.task_graph[task_id]
        if task["status"] != "pending":
            return False

        task["status"] = "decomposing"
        self.update_task_status(task_id, "decomposing", 0)

        if decomposition_strategy == "recursive":
            self._recursive_decompose(task_id)
        elif decomposition_strategy == "flat":
            self._flat_decompose(task_id)
        else:
            return False

        self.update_task_status(task_id, "completed", 100)
        return True

    def _recursive_decompose(self, task_id: str) -> None:
        task = self.task_graph[task_id]
        if task["status"] != "decomposing":
            return

        task["progress"] = 20
        self.update_task_status(task_id, "decomposing", 20)

        if not task["dependencies"]:
            task["status"] = "completed"
            self.update_task_status(task_id, "completed", 100)
            return

        for dep in task["dependencies"]:
            if dep not in self.task_graph:
                self.update_task_status(task_id, "error", 0, f"Dependency {dep} not found")
                return

        task["progress"] = 40
        self.update_task_status(task_id, "decomposing", 40)

        for dep in task["dependencies"]:
            self.create_task(
                self.generate_task_id(),
                f"{task['name']}_subtask",
                f"Subtask for {task['name']}",
                dependencies=[],
                parent_id=task_id
            )

        task["progress"] = 60
        self.update_task_status(task_id, "decomposing", 60)

        for child in self.task_graph[task_id]["children"]:
            self.decompose_task(child, "recursive")

        task