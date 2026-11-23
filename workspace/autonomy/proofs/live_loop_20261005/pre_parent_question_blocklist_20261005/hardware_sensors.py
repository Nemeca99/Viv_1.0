"""Bounded, read-only snapshots from configured HWiNFO and Corsair CSV logs."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import time


HARDWARE_LOG_ROOT = Path(r"L:\LocalCoder\Hardware")
SENSOR_STALE_AFTER_SECONDS = 15.0
MAX_SENSOR_TAIL_BYTES = 512 * 1024

SENSOR_DEFINITIONS = {
    "hwinfo": {
        "filename": "hwinfo.CSV",
        "timestamp_fields": ("Date", "Time"),
        "fields": (
            "CPU Package", "Core Temperatures (avg)", "CPU Package Power",
            "Core Thermal Throttling (avg)", "Package/Ring Thermal Throttling",
            "PCH Temperature", "VR VCC Temperature", "Chassis [RPM]",
            "Power [RPM]", "Fan4 [RPM]", "Coolant Temperature",
            "GPU Temperature", "GPU Hot Spot Temperature", "GPU Power [W]",
            "GPU Core Load", "GPU Memory Usage", "GPU Fan1 [RPM]",
            "GPU Fan2 [RPM]", "Drive Temperature", "Drive Remaining Life",
        ),
    },
    "corsair": {
        "filename": None,
        "timestamp_fields": ("Timestamp",),
        "fields": (
            "CPU Package", "CPU Load", "GPU Temp #1", "GPU Temp #2",
            "GPU Load", "MB Fan #1", "MB Fan #2", "MB Fan #3",
            "H100i ELITE CAPELLIX Fan #1", "H100i ELITE CAPELLIX Fan #2",
            "H100i ELITE CAPELLIX Pump", "H100i ELITE CAPELLIX Coolant Temp",
        ),
    },
}

TIMESTAMP_FORMATS = (
    "%d.%m.%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S %p",
    "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
)


def read_external_sensor_logs(root: Path | str = HARDWARE_LOG_ROOT, *, now: float | None = None) -> dict:
    """Read the latest complete rows, bounded to the header and final 512 KiB per CSV."""
    root = Path(root)
    now = time.time() if now is None else float(now)
    paths = {"hwinfo": root / SENSOR_DEFINITIONS["hwinfo"]["filename"]}
    corsair_candidates = []
    try:
        for path in root.glob("corsair_cue_*.csv"):
            try:
                corsair_candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
    except OSError:
        pass
    if corsair_candidates:
        paths["corsair"] = max(corsair_candidates, key=lambda pair: pair[0])[1]
    else:
        paths["corsair"] = root / "corsair_cue_20261004_21_45_09.csv"

    result = {}
    for name, spec in SENSOR_DEFINITIONS.items():
        path = paths[name]
        feed = {"path": str(path), "available": False}
        try:
            stat = path.stat()
            file_age = max(0.0, now - stat.st_mtime)
            feed.update({"available": True, "file_size_bytes": stat.st_size,
                         "file_age_seconds": round(file_age, 1),
                         "stale": file_age > SENSOR_STALE_AFTER_SECONDS})
            if stat.st_size <= 0:
                feed["error"] = "empty_file"
                result[name] = feed
                continue
            with path.open("rb") as stream:
                header_bytes = stream.readline()
                header = header_bytes.decode("utf-8-sig", errors="replace")
                encoding = "utf-8"
                if "\ufffd" in header:
                    encoding = "cp1252"
                    header = header_bytes.decode(encoding, errors="replace")
                header = header.rstrip("\r\n")
                start = max(len(header_bytes), stat.st_size - MAX_SENSOR_TAIL_BYTES)
                stream.seek(start)
                if start > len(header_bytes):
                    stream.readline()
                tail = stream.read(MAX_SENSOR_TAIL_BYTES).decode(encoding, errors="replace")
            parsed = list(csv.reader([header, *tail.splitlines()]))
            columns = parsed[0] if parsed else []
            row = next((candidate for candidate in reversed(parsed[1:])
                        if len(candidate) == len(columns)), None)
            if row is None:
                feed["error"] = "no_complete_csv_row"
                result[name] = feed
                continue
            data = dict(zip(columns, row))
            timestamp = " ".join(data.get(key, "").strip()
                                 for key in spec["timestamp_fields"]).strip()
            feed["sample_timestamp"] = timestamp or None
            parsed_time = None
            for fmt in TIMESTAMP_FORMATS:
                try:
                    parsed_time = datetime.strptime(timestamp, fmt)
                    break
                except (ValueError, TypeError):
                    continue
            if parsed_time is not None:
                sample_age = max(0.0, now - parsed_time.timestamp())
                feed["sample_age_seconds"] = round(sample_age, 1)
                feed["stale"] = sample_age > SENSOR_STALE_AFTER_SECONDS
            selected = {}
            for wanted in spec["fields"]:
                matches = [key for key in columns if key == wanted]
                if not matches:
                    matches = [key for key in columns if key.startswith(wanted + " ")]
                for key in matches[:3]:
                    value = data.get(key, "").strip()
                    if value:
                        selected[key] = value
            feed["readings"] = selected
            result[name] = feed
        except FileNotFoundError:
            feed["error"] = "file_not_found"
            result[name] = feed
        except (OSError, csv.Error, UnicodeError) as exc:
            feed["error"] = type(exc).__name__
            result[name] = feed
    return result


def body_sense_snapshot(*, now: float | None = None, root: Path | str = HARDWARE_LOG_ROOT) -> dict:
    """Describe actual channels and include dated instrument readings without anthropomorphizing them."""
    observed_utc = datetime.fromtimestamp(time.time() if now is None else now,
                                          tz=timezone.utc).isoformat()
    return {
        "observed_utc": observed_utc,
        "channels": {
            "sight": "task-supplied file text, metadata, index, or receipt; no camera input",
            "hearing": "unavailable: no microphone/audio-perception input; typed chat is text",
            "touch": "unavailable: no haptic/contact sensor; telemetry is instrumented body-state data, not touch",
            "taste": "unavailable: no taste/chemical sensor",
            "smell": "unavailable: no smell/chemical sensor",
            "body_state_instrumentation": "timestamped HWiNFO and Corsair CSV readings when available",
        },
        "sensor_topology": {
            "cpu_loop": "CPU package, H100i coolant, pump, and H100i radiator fans describe the CPU liquid-cooling loop.",
            "gpu_domain": "GPU temperature and GPU fans describe the separate air-cooled GPU; H100i coolant does not measure GPU temperature.",
            "interpretation": "A single or stale reading does not establish a trend or diagnose a component failure.",
        },
        "stale_after_seconds": SENSOR_STALE_AFTER_SECONDS,
        "external_sensor_logs": read_external_sensor_logs(root, now=now),
    }
