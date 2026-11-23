import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

class SecurityCore:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.key_rotation_interval = config.get("key_rotation_interval", 7)
        self.aead_key_cache: Dict[str, Dict[str, Any]] = {}
        self.privilege_map: Dict[str, Dict[str, Any]] = {}
        self.health_status = {
            "status": "healthy",
            "last_key_rotation": None,
            "last_health_check": None
        }

    def load_config(self):
        if not self.config:
            raise ValueError("Configuration is required for SecurityCore")
        if "aead_keys" not in self.config:
            raise ValueError("AEAD keys configuration is missing")
        if "privileges" not in self.config:
            raise ValueError("Privilege configuration is missing")

        for key_id, key_data in self.config["aead_keys"].items():
            self.aead_key_cache[key_id] = {
                "key": key_data["key"],
                "valid_from": key_data.get("valid_from", datetime.now()),
                "valid_to": key_data.get("valid_to", datetime.now() + timedelta(days=self.key_rotation_interval))
            }

        for endpoint, privileges in self.config["privileges"].items():
            self.privilege_map[endpoint] = {
                "privileges": privileges,
                "last_access": None
            }

    def validate_aead_key(self, key_id: str) -> bool:
        if key_id not in self.aead_key_cache:
            return False

        key_data = self.aead_key_cache[key_id]
        current_time = datetime.now()

        if current_time < key_data["valid_from"] or current_time > key_data["valid_to"]:
            return False

        return True

    def check_endpoint_privilege(self, endpoint: str, required_privilege: str) -> bool:
        if endpoint not in self.privilege_map:
            return False

        privileges = self.privilege_map[endpoint]["privileges"]
        if required_privilege not in privileges:
            return False

        return True

    def rotate_aead_keys(self):
        current_time = datetime.now()
        for key_id, key_data in self.aead_key_cache.items():
            if current_time >= key_data["valid_to"]:
                new_key = self.generate_new_key()
                self.aead_key_cache[key_id]["key"] = new_key
                self.aead_key_cache[key, "valid_from"] = current_time
                self.aead_key_cache[key_id]["valid_to"] = current_time + timedelta(days=self.key_rotation_interval)

        self.health_status["last_key_rotation"] = current_time
        self.health_status["status"] = "healthy"

    def generate_new_key(self) -> str:
        return os.urandom(32).hex()

    def check_health(self) -> Dict[str, Any]:
        current_time = datetime.now()
        self.health_status["last_health_check"] = current_time

        if not self.aead_key_cache:
            self.health_status["status"] = "unhealthy"
            self.health_status["error"] = "No AEAD keys loaded"
            return self.health_status

        for key_id, key_data in self.aead_key_cache.items():
            if key_data["valid_to"] < current_time:
                self.health_status["status"] = "unhealthy"
                self.health_status["error"] = f"Key {key_id} is expired"
                return self.health_status

        self.health_status["status"] = "healthy"
        return self.health_status

    def get_health_status(self) -> Dict[str, Any]:
        return self.health_status.copy()

def main(config: Dict[str, Any]):
    security_core = SecurityCore(config)
    security_core.load_config()
    return security_core