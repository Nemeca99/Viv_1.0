import os
import hashlib
import json
import time
from datetime import datetime

class BackupCore:
    def __init__(self, config):
        self.config = config
        self.snapshot_dir = config.get('snapshot_dir', '.snapshots')
        self.max_snapshots = config.get('max_snapshots', 5)
        self.snapshot_hashes = {}
        self.last_snapshot_time = 0
        self.health_status = {
            'status': 'healthy',
            'last_snapshot': None,
            'snapshot_count': 0,
            'quota_used': 0,
            'quota_limit': config.get('quota_limit', 1000000000)
        }
        self._init_snapshot_dir()

    def _init_snapshot_dir(self):
        if not os.path.exists(self.snapshot_dir):
            os.makedirs(self.snapshot_dir)

    def _generate_snapshot_name(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{timestamp}.snapshot"

    def _calculate_hash(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _verify_hashes(self):
        for snapshot_file in os.listdir(self.snapshot_dir):
            snapshot_path = os.path.join(self.snapshot_dir, snapshot_file)
            if os.path.isfile(snapshot_path):
                try:
                    with open(snapshot_path, 'r') as f:
                        data = json.load(f)
                    snapshot_id = data.get('id')
                    file_hash = data.get('hash')
                    if snapshot_id in self.snapshot_hashes:
                        if self.snapshot_hashes[snapshot_id] != file_hash:
                            print(f"Hash mismatch for snapshot {snapshot_id}")
                except Exception as e:
                    print(f"Error reading snapshot {snapshot_file}: {e}")

    def _manage_snapshot_quota(self):
        snapshot_files = [f for f in os.listdir(self.snapshot_dir) if os.path.isfile(os.path.join(self.snapshot_dir, f))]
        if len(snapshot_files) > self.max_snapshots:
            oldest_snapshot = min(snapshot_files, key=lambda x: os.path.getctime(os.path.join(self.snapshot_dir, x)))
            os.remove(os.path.join(self.snapshot_dir, oldest_snapshot))
            print(f"Removed oldest snapshot {oldest_snapshot} to stay within quota")

    def _create_snapshot(self, file_path):
        snapshot_name = self._generate_snapshot_name()
        snapshot_path = os.path.join(self.snapshot_dir, snapshot_name)
        file_hash = self._calculate_hash(file_path)
        snapshot_data = {
            'id': snapshot_name,
            'timestamp': datetime.now().isoformat(),
            'file_hash': file_hash,
            'file_path': file_path
        }
        with open(snapshot_path, 'w') as f:
            json.dump(snapshot_data, f)
        self.snapshot_hashes[snapshot_name] = file_hash
        self._manage_snapshot_quota()
        self._verify_hashes()
        self._update_health_status()

    def _update_health_status(self):
        self.health_status['last_snapshot'] = datetime.now().isoformat()
        self.health_status['snapshot_count'] = len(os.listdir(self.snapshot_dir))
        self.health_status['quota_used'] = sum(os.path.getsize(os.path.join(self.snapshot_dir, f)) for f in os.listdir(self.snapshot_dir) if os.path.isfile(os.path.join(self.snapshot_dir, f)))
        self.health_status['status'] = 'healthy' if self.health_status['quota_used'] <= self.health_status['quota_limit'] else 'over_quota'

    def get_health_status(self):
        return self.health_status

    def backup_file(self, file_path):
        if os.path.exists(file_path):
            self._create_snapshot(file_path)
        else:
            print(f"File {file_path} does not exist.")

if __name__ == "__main__":
    config = {
        'snapshot_dir': '.snapshots',
        'max_snapshots': 5,
        'quota_limit': 1000000000
    }
    backup_core = BackupCore(config)
    backup_core.backup_file('example.txt')
    print(backup_core.get_health_status())