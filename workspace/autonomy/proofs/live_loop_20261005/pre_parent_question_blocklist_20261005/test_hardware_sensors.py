from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest

from autonomy.hardware_sensors import body_sense_snapshot, read_external_sensor_logs


class HardwareSensorSnapshotTests(unittest.TestCase):
    def test_reads_latest_selected_values_and_marks_fresh_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "hwinfo.CSV"
            path.write_text(
                "Date,Time,CPU Package [C],GPU Temperature [C],Coolant Temperature [C]\n"
                "05.10.2026,03:00:00.000,45,52,31\n",
                encoding="utf-8",
            )
            stamp = datetime.strptime("05.10.2026 03:00:00.000", "%d.%m.%Y %H:%M:%S.%f").timestamp()
            os.utime(path, (stamp, stamp))

            snapshot = read_external_sensor_logs(root, now=stamp + 10)

        hwinfo = snapshot["hwinfo"]
        self.assertTrue(hwinfo["available"])
        self.assertFalse(hwinfo["stale"])
        self.assertEqual(hwinfo["sample_age_seconds"], 10.0)
        self.assertEqual(hwinfo["readings"]["CPU Package [C]"], "45")
        self.assertEqual(hwinfo["readings"]["GPU Temperature [C]"], "52")
        self.assertEqual(hwinfo["readings"]["Coolant Temperature [C]"], "31")
        self.assertEqual(snapshot["corsair"]["error"], "file_not_found")

    def test_stale_feed_is_not_reported_as_live_in_body_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "hwinfo.CSV"
            path.write_text(
                "Date,Time,CPU Package [C]\n05.10.2026,03:00:00.000,45\n",
                encoding="utf-8",
            )
            stamp = datetime.strptime("05.10.2026 03:00:00.000", "%d.%m.%Y %H:%M:%S.%f").timestamp()
            os.utime(path, (stamp, stamp))

            snapshot = body_sense_snapshot(root=root, now=stamp + 20)

        self.assertTrue(snapshot["external_sensor_logs"]["hwinfo"]["stale"])
        self.assertEqual(snapshot["stale_after_seconds"], 15.0)
        self.assertIn("not touch", snapshot["channels"]["touch"])
        self.assertIn("H100i coolant does not measure GPU", snapshot["sensor_topology"]["gpu_domain"])
        self.assertIn("unavailable", snapshot["channels"]["taste"])
        self.assertIn("unavailable", snapshot["channels"]["smell"])

    def test_sensor_absence_is_reported_without_fabricating_zero_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = read_external_sensor_logs(tmp, now=1_800_000_000)
        self.assertFalse(snapshot["hwinfo"]["available"])
        self.assertEqual(snapshot["hwinfo"]["error"], "file_not_found")
        self.assertNotIn("readings", snapshot["hwinfo"])


if __name__ == "__main__":
    unittest.main()
