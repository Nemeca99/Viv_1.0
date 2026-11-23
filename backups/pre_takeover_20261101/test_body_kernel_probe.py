import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "aios_rebuild"))

from body_runtime import kernel_probe


class BodyKernelProbeTests(unittest.TestCase):
    def test_body_health_and_expected_inventory_are_generated_in_container(self):
        container_health = {
            "kernel": "healthy",
            "cores": {"security_core": {"status": "healthy"}},
        }
        caller_resources = {"requested_threads": 2, "thermal_samples": []}
        request = {
            "body_resources": caller_resources,
            "candidate_run_id": "candidate-1",
        }

        with patch.object(kernel_probe, "_body_health", return_value=container_health):
            rust_request = kernel_probe._build_rust_request(request)

        self.assertEqual(rust_request["health"], container_health)
        self.assertEqual(rust_request["expected_cores"], [])
        self.assertEqual(rust_request["body_resources"], caller_resources)
        self.assertEqual(rust_request["candidate_run_id"], "candidate-1")

    def test_rejects_unknown_fields_and_missing_resources(self):
        for request in (
            {"body_resources": {}, "command": "sh"},
            {"health": {"kernel": "healthy"}},
            {"body_resources": {}, "health": {"kernel": "spoofed"}},
            {"body_resources": {}, "expected_cores": ["spoofed_core"]},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                kernel_probe._build_rust_request(request)


if __name__ == "__main__":
    unittest.main()
