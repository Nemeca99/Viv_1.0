from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import uuid
import json
import time
import os
import logging

logging.basicConfig(level=logging.INFO)

@dataclass
class Event:
    event_id: str
    event_type: str
    data: Dict[str, Any]
    timestamp: float

@dataclass
class ProjectionState:
    version: int
    data: Dict[str, Any]
    last_event_id: str
    last_event_time: float

class DataCore:
    def __init__(self, storage_dir: str = "data_core_storage"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.projections: Dict[str, ProjectionState] = {}
        self.load_projections()

    def load_projections(self):
        for filename in os.listdir(self.storage_dir):
            if filename.endswith(".json"):
                projection_id = filename[:-5]
                file_path = os.path.join(self.storage_dir, filename)
                with open(file_path, "r") as f:
                    state = json.load(f)
                self.projections[projection_id] = ProjectionState(**state)

    def save_projection(self, projection_id: str, state: ProjectionState):
        file_path = os.path.join(self.storage_dir, f"{projection_id}.json")
        with open(file_path, "w") as f:
            json.dump(state.__dict__, f)

    def apply_event(self, projection_id: str, event: Event):
        if projection_id not in self.projections:
            self.projections[projection_id] = ProjectionState(
                version=0,
                data={},
                last_event_id="",
                last_event_time=0
            )

        state = self.projections[projection_id]
        if event.event_id > state.last_event_id:
            state.version += 1
            state.data = self.apply_event_to_state(state.data, event)
            state.last_event_id = event.event_id
            state.last_event_time = event.timestamp
            self.save_projection(projection_id, state)
            return True
        return False

    def apply_event_to_state(self, state: Dict[str, Any], event: Event):
        try:
            handler = getattr(self, f"handle_{event.event_type}", None)
            if handler:
                return handler(state, event)
            return state
        except Exception as e:
            logging.error(f"Error applying event {event.event_id}: {str(e)}")
            return state

    def handle_user_created(self, state: Dict[str, Any], event: Event):
        return {
            **state,
            "user_id": event.data.get("user_id"),
            "username": event.data.get("username"),
            "created_at": event.timestamp
        }

    def handle_user_updated(self, state: Dict[str, Any], event: Event):
        return {
            **state,
            "username": event.data.get("username"),
            "updated_at": event.timestamp
        }

    def get_projection(self, projection_id: str) -> Optional[ProjectionState]:
        return self.projections.get(projection_id)

    def list_projections(self) -> List[str]:
        return list(self.projections.keys())

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "projections_count": len(self.projections),
            "storage_dir": self.storage_dir,
            "timestamp": time.time()
        }

    def replay_events(self, projection_id: str, events: List[Event]):
        for event in events:
            if self.apply_event(projection_id, event):
                logging.info(f"Replayed event {event.event_id} for projection {projection_id}")
            else:
                logging.warning(f"Skipped event {event.event_id} for projection {projection_id}")

    def get_event(self, event_id: str) -> Optional[Event]:
        for proj in self.projections.values():
            if proj.last_event_id == event_id:
                return Event(
                    event_id=event_id,
                    event_type="unknown",
                    data={},
                    timestamp=proj.last_event_time
                )
        return None

    def get_all_events(self) -> List[Event]:
        events = []
        for proj in self.projections.values():
            if proj.last_event_id:
                events.append(Event(
                    event_id=proj.last_event_id,
                    event_type="unknown",
                    data={},
                    timestamp=proj.last_event_time
                ))
        return events