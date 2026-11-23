import os
import tempfile
import shutil
import unittest
from backup_core import BackupCore


class TestBackupCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = {
            'snapshot_dir': os.path.join(self.temp_dir, '.snapshots'),
            'max_snapshots': 3,
            'quota_limit': 100
        }

    def test_init_default_config(self):
        bc = BackupCore({'snapshot_dir': '/tmp/test', 'max_snapshots': 5})
        self.assertEqual(bc.max_snapshots, 5)
        self.assertEqual(bc.quota_limit, 1000000000)

    def test_backup_file_basic(self):
        bc = BackupCore(self.config)
        src_path = os.path.join(self.temp_dir, 'test.txt')
        with open(src_path, 'w') as f:
            f.write('hello world')
        bc.backup_file(src_path)
        snap_path = os.path.join(bc.snapshot_dir, 'test.snap')
        self.assertTrue(os.path.exists(snap_path))

    def test_backup_file_missing(self):
        bc = BackupCore(self.config)
        with self.assertRaises(FileNotFoundError):
            bc.backup_file('/nonexistent/path.txt')

    def test_calculate_hash(self):
        bc = BackupCore(self.config)
        src_path = os.path.join(self.temp_dir, 'hash_test.txt')
        with open(src_path, 'w') as f:
            f.write('test content')
        hash_val = bc._calculate_hash(src_path)
        self.assertEqual(len(hash_val), 64)

    def test_manage_snapshot_quota(self):
        bc = BackupCore({'snapshot_dir': os.path.join(self.temp_dir, '.snap'), 'max_snapshots': 2})
        for i in range(5):
            src = f'test{i}.txt'
            with open(src, 'w') as f:
                f.write('x' * 10)
            bc.backup_file(src)
        self.assertEqual(len([f for f in os.listdir(bc.snapshot_dir) if f.endswith('.snap')]), 2)

    def test_verify_hashes_valid(self):
        bc = BackupCore({'snapshot_dir': os.path.join(self.temp_dir, '.snap'), 'max_snapshots': 5})
        src_path = os.path.join(self.temp_dir, 'verify.txt')
        with open(src_path, 'w') as f:
            f.write('verification data')
        bc.backup_file(src_path)
        self.assertTrue(bc._verify_hashes())

    def test_verify_hashes_missing(self):
        bc = BackupCore({'snapshot_dir': os.path.join(self.temp_dir, '.snap'), 'max_snapshots': 5})
        src_path = os.path.join(self.temp_dir, 'missing.txt')
        with open(src_path, 'w') as f:
            f.write('data')
        bc.backup_file(src_path)
        # Remove snapshot file to test missing hash verification
        snap_path = os.path.join(bc.snapshot_dir, 'missing.snap')
        if os.path.exists(snap_path):
            os.remove(snap_path)
        self.assertFalse(bc._verify_hashes())

    def test_get_health_status(self):
        bc = BackupCore({'snapshot_dir': os.path.join(self.temp_dir, '.snap'), 'quota_limit': 100})
        src_path = os.path.join(self.temp_dir, 'health.txt')
        with open(src_path, 'w') as f:
            f.write('x' * 50)
        bc.backup_file(src_path)
        status = bc.get_health_status()
        self.assertIn('status', status)
        self.assertIn('snapshot_count', status)

    def test_quota_exceeded(self):
        bc = BackupCore({'snapshot_dir': os.path.join(self.temp_dir, '.snap'), 'quota_limit': 10})
        for i in range(5):
            src = f'quota{i}.txt'
            with open(src, 'w') as f:
                f.write('x' * 3)
            bc.backup_file(src)
        status = bc.get_health_status()
        self.assertEqual(status['status'], 'over_quota')


if __name__ == '__main__':
    unittest.main()