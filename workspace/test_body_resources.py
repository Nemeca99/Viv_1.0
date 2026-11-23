from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest

from aios_rebuild.main_core.body_resources import collect_body_resources
from autonomy.hardware_sensors import read_external_sensor_logs


class BodyResourceSnapshotTests(unittest.TestCase):
    def test_collects_fresh_sensor_and_workspace_resource_readings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime.now().astimezone()
            timestamp = now.strftime("%d.%m.%Y,%H:%M:%S.000")
            sensor_file = root / "hwinfo.CSV"
            sensor_file.write_text(
                "Date,Time,CPU Package [C],GPU Temperature [C],GPU Core Load [%],GPU Memory Usage [%],GPU Power [W]\n"
                f"{timestamp},55,62,20,27.2,75\n",
                encoding="utf-8",
            )
            stamp = now.timestamp()
            os.utime(sensor_file, (stamp, stamp))

            resources = collect_body_resources(sensor_root=root, workspace_root=root)

        self.assertLessEqual(resources["sensor_age_seconds"], 15.0)
        self.assertEqual(resources["cpu_temp_c"], 55.0)
        self.assertEqual(resources["gpu_temp_c"], 62.0)
        self.assertEqual(resources["gpu_core_load_percent"], 20.0)
        self.assertEqual(resources["gpu_memory_percent"], 27.2)
        self.assertEqual(resources["gpu_power_w"], 75.0)
        self.assertEqual(resources["requested_threads"], 1)
        self.assertEqual(len(resources["thermal_samples"]), 1)
        self.assertEqual(resources["thermal_samples"][0]["source"], "hwinfo")
        self.assertIsNotNone(resources["ram_percent"])
        self.assertIsNotNone(resources["workspace_disk_free_percent"])
        self.assertGreater(resources["workspace_disk_free_bytes"], 0)

    def test_missing_hardware_readings_remain_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = collect_body_resources(sensor_root=temporary, workspace_root=temporary)

        self.assertIsNone(resources["sensor_age_seconds"])
        self.assertIsNone(resources["cpu_temp_c"])
        self.assertIsNone(resources["gpu_temp_c"])
        self.assertIsNone(resources["gpu_memory_percent"])
        self.assertEqual(resources["thermal_samples"], [])

    def test_gpu_memory_is_unavailable_when_hwinfo_sample_is_stale(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = datetime.now().astimezone().replace(year=2020)
            sensor_file = root / "hwinfo.CSV"
            sensor_file.write_text(
                "Date,Time,CPU Package [C],GPU Temperature [C],GPU Memory Usage [%]\n"
                f"{stale.strftime('%d.%m.%Y,%H:%M:%S.000')},55,62,27.2\n",
                encoding="utf-8",
            )
            stamp = stale.timestamp()
            os.utime(sensor_file, (stamp, stamp))
            resources = collect_body_resources(sensor_root=root, workspace_root=root)

        self.assertIsNone(resources["gpu_memory_percent"])

    def test_corsair_unit_suffixes_are_numeric_for_thermal_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime.now().astimezone()
            hwinfo = root / "hwinfo.CSV"
            hwinfo.write_text(
                "Date,Time,CPU Package [C]\n"
                f"{now.strftime('%d.%m.%Y')},{now.strftime('%H:%M:%S')}.000,45\n",
                encoding="utf-8",
            )
            corsair = root / "corsair_cue_test.csv"
            corsair.write_text(
                "Timestamp,CPU Package,GPU Temp #1,GPU Temp #2\n"
                f"{now.strftime('%m/%d/%Y %I:%M:%S %p')},45.00°C,55.72°C,67.16°C\n",
                encoding="utf-8",
            )
            stamp = now.timestamp()
            os.utime(hwinfo, (stamp, stamp))
            os.utime(corsair, (stamp, stamp))
            sensor_feeds = read_external_sensor_logs(root)

            resources = collect_body_resources(sensor_root=root, workspace_root=root)

        self.assertFalse(sensor_feeds["corsair"]["stale"])
        self.assertLessEqual(sensor_feeds["corsair"]["sample_age_seconds"], 15.0)
        corsair_samples = [sample for sample in resources["thermal_samples"]
                           if sample["source"] == "corsair"]
        self.assertEqual([sample["gpu_temp_c"] for sample in corsair_samples], [55.72, 67.16])
        self.assertTrue(all(sample["cpu_temp_c"] == 45.0 for sample in corsair_samples))

    def test_corsair_24_hour_timestamp_with_pm_suffix_has_real_sample_age(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime.now().astimezone()
            hwinfo = root / "hwinfo.CSV"
            hwinfo.write_text(
                "Date,Time,CPU Package [C]\n"
                f"{now.strftime('%d.%m.%Y')},{now.strftime('%H:%M:%S')}.000,45\n",
                encoding="utf-8",
            )
            corsair = root / "corsair_cue_test.csv"
            corsair.write_text(
                "Timestamp,CPU Package,GPU Temp #1\n"
                f"{now.strftime('%d/%m/%Y %H:%M:%S')} PM,45.00°C,55.72°C\n",
                encoding="utf-8",
            )
            stamp = now.timestamp()
            os.utime(hwinfo, (stamp, stamp))
            os.utime(corsair, (stamp, stamp))

            sensor_feeds = read_external_sensor_logs(root)

        self.assertLessEqual(sensor_feeds["corsair"]["sample_age_seconds"], 15.0)
        self.assertFalse(sensor_feeds["corsair"]["stale"])


if __name__ == "__main__":
    unittest.main()
