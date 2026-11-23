import time
import uuid
from datetime import datetime, timedelta

class CarmaCore:
    def __init__(self):
        self.memory_mycelium = {}
        self.health_status = {
            'status': 'healthy',
            'last_check_time': datetime.now().isoformat(),
            'memory_usage': 0,
            'decay_rate': 0.01,
            'vector_dim': 128
        }

    def _generate_id(self):
        return str(uuid.uuid4())

    def _apply_decay(self, memory):
        decay_factor = self.health_status['decay_rate']
        memory['vector'] = [v * (1 - decay_factor) for v in memory['vector']]
        memory['timestamp'] = datetime.now().isoformat()

    def _check_memory_decay(self):
        current_time = datetime.now().isoformat()
        for mem_id, memory in list(self.memory_mycelium.items()):
            if (datetime.fromisoformat(current_time) - 
                datetime.fromisoformat(memory['timestamp'])) > timedelta(hours=24):
                self._apply_decay(memory)
                self.memory_mycelium[mem_id] = memory

    def _update_health_status(self):
        self.health_status['last_check_time'] = datetime.now().isoformat()
        self.health_status['memory_usage'] = len(self.memory_mycelium)
        self.health_status['status'] = 'healthy'

    def add_semantic_memory(self, content, vector):
        mem_id = self._generate_id()
        self.memory_mycelium[mem_id] = {
            'id': mem_id,
            'content': content,
            'vector': vector,
            'timestamp': datetime.now().isoformat()
        }
        self._update_health_status()

    def retrieve_memory(self, query, threshold=0.8):
        results = []
        for mem_id, memory in self.memory_mycelium.items():
            if self._similarity(memory['vector'], query) > threshold:
                results.append(memory)
        return results

    def _similarity(self, vec1, vec2):
        if len(vec1) != len(vec2):
            return 0.0
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a**2 for a in vec1) ** 0.5
        norm2 = sum(b**2 for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)

    def get_health_status(self):
        self._check_memory_decay()
        self._update_health_status()
        return self.health_status

    def run_health_check(self):
        self._check_memory_decay()
        self._update_health_status()


# Compatibility alias for enterprise_core and legacy interfaces
CARMASystem = CarmaCore
