import hashlib
import os
import shutil


class BackupCore:
    def __init__(self, config: dict):
        self.config = config
        snapshot_dir = config.get('snapshot_dir', '.snapshots')
        os.makedirs(snapshot_dir, exist_ok=True)
        self.snapshot_dir = snapshot_dir
        self.max_snapshots = config.get('max_snapshots', 5)
        self.quota_limit = config.get('quota_limit', 1000000000)
        self.snapshot_hashes = {}

    def _calculate_hash(self, file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def backup_file(self, file_path: str):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f'File not found: {file_path}')
        
        hash_val = self._calculate_hash(file_path)
        
        # Get basename without extension for snapshot name
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        snapshot_name = f'{base_name}.snap'
        dest_path = os.path.join(self.snapshot_dir, snapshot_name)
        
        if os.path.exists(dest_path):
            os.remove(dest_path)
        
        shutil.copy2(file_path, dest_path)
        self.snapshot_hashes[dest_path] = hash_val
        
        # Manage quota after backup
        self._manage_snapshot_quota()

    def _manage_snapshot_quota(self):
        snap_files = sorted([f for f in os.listdir(self.snapshot_dir) if f.endswith('.snap')])
        while len(snap_files) > self.max_snapshots:
            oldest_name = snap_files.pop(0)
            oldest_path = os.path.join(self.snapshot_dir, oldest_name)
            if os.path.exists(oldest_path):
                os.remove(oldest_path)
                del self.snapshot_hashes[oldest_path]

    def _verify_hashes(self) -> bool:
        if not self.snapshot_hashes:
            return False
        
        for path, expected_hash in list(self.snapshot_hashes.items()):
            if not os.path.exists(path):
                return False
            actual_hash = self._calculate_hash(path)
            if actual_hash != expected_hash:
                return False
        
        return True

    def get_health_status(self) -> dict:
        snap_files = [f for f in os.listdir(self.snapshot_dir) if f.endswith('.snap')]
        snapshot_count = len(snap_files)
        
        total_size = 0
        for f in sorted(snap_files):
            full_path = os.path.join(self.snapshot_dir, f)
            if os.path.exists(full_path):
                total_size += os.path.getsize(full_path)
        
        status = 'healthy' if total_size <= self.quota_limit else 'over_quota'
        return {'status': status, 'snapshot_count': snapshot_count, 'quota_limit': total_size}


if __name__ == '__main__':
    import unittest
    from backup_core_test import TestBackupCore
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBackupCore)
    unittest.TextTestRunner().run(suite)