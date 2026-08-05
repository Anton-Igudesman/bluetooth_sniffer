import json
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from bluetooth_sniffer.display.session import create_live_session_paths
from bluetooth_sniffer.event_log import EventLogger


class LiveSessionPathsTests(unittest.TestCase):
    def test_builds_one_directory_for_all_session_artifacts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            capture_directory = Path(temporary_directory)
            paths = create_live_session_paths(
                capture_directory,
                "AA:BB:CC:DD:EE:FF",
                started_at=datetime(
                    2026,
                    8,
                    5,
                    12,
                    34,
                    56,
                    789,
                    tzinfo=UTC,
                ),
            )

            self.assertEqual(
                paths.directory,
                capture_directory
                / "touchscreen-20260805T123456000789Z-aabbccddeeff",
            )
            self.assertTrue(paths.directory.is_dir())
            self.assertEqual(
                paths.event_log,
                paths.directory / "session.jsonl",
            )
            self.assertEqual(paths.pcap, paths.directory / "capture.pcap")
            self.assertEqual(
                paths.correlation_report,
                paths.directory / "correlation.json",
            )

    def test_normalizes_session_timestamp_to_utc(self) -> None:
        pacific = timezone(timedelta(hours=-7))
        with TemporaryDirectory() as temporary_directory:
            paths = create_live_session_paths(
                Path(temporary_directory),
                "device-1",
                started_at=datetime(2026, 8, 5, 5, 0, tzinfo=pacific),
            )

            self.assertEqual(
                paths.directory.name,
                "touchscreen-20260805T120000000000Z-device1",
            )

    def test_rejects_naive_session_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            with TemporaryDirectory() as temporary_directory:
                create_live_session_paths(
                    Path(temporary_directory),
                    "AA:BB",
                    started_at=datetime(2026, 8, 5),
                )

    def test_suffixes_a_session_directory_collision(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            capture_directory = Path(temporary_directory)
            started_at = datetime(2026, 8, 5, tzinfo=UTC)
            first_paths = create_live_session_paths(
                capture_directory,
                "AA:BB",
                started_at=started_at,
            )

            second_paths = create_live_session_paths(
                capture_directory,
                "AA:BB",
                started_at=started_at,
            )

            self.assertNotEqual(first_paths.directory, second_paths.directory)
            self.assertTrue(second_paths.directory.name.endswith("-1"))


class TouchscreenEventLogCompatibilityTests(unittest.TestCase):
    def test_session_directory_is_created_by_first_event(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            event_log = Path(temporary_directory) / "session" / "session.jsonl"
            logger = EventLogger(event_log)

            logger.record(
                "gatt.write",
                service_uuid="0000180f-0000-1000-8000-00805f9b34fb",
                characteristic_uuid="00002a19-0000-1000-8000-00805f9b34fb",
                payload_hex="01",
                payload_size_bytes=1,
                write_mode="with-response",
            )

            record = json.loads(event_log.read_text(encoding="utf-8"))
            self.assertEqual(record["event"], "gatt.write")
            self.assertEqual(record["payload_hex"], "01")
            self.assertIn("timestamp", record)


if __name__ == "__main__":
    unittest.main()
