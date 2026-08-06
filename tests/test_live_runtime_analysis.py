import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from bluetooth_sniffer.display.live_runtime import (
    AnalysisCompleted,
    LiveRuntime,
    RuntimeFailed,
)
from bluetooth_sniffer.event_log import EventLogger


class LiveRuntimeAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_completed_update_after_writing_report(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            event_log_path = directory / "session.jsonl"
            pcap_path = directory / "capture.pcap"
            report_path = directory / "correlation.json"
            correlations = [Mock(matched=True), Mock(matched=False)]
            runtime = LiveRuntime()
            runtime._event_logger = EventLogger(event_log_path)

            with (
                patch(
                    "bluetooth_sniffer.display.live_runtime.analyze_session",
                    new=AsyncMock(return_value=correlations),
                ) as analyze_session,
                patch(
                    "bluetooth_sniffer.display.live_runtime.write_correlation_report"
                ) as write_report,
            ):
                await runtime._analyze_completed_session(
                    event_log_path,
                    pcap_path,
                    report_path,
                )

            analyze_session.assert_awaited_once_with(
                event_log_path,
                pcap_path,
            )
            write_report.assert_called_once()
            updates = runtime.drain_updates()
            self.assertEqual(len(updates), 1)
            self.assertEqual(
                updates[0],
                AnalysisCompleted(
                    event_log_path=event_log_path,
                    pcap_path=pcap_path,
                    report_path=report_path,
                    matched_count=1,
                    event_count=2,
                ),
            )

            record = json.loads(event_log_path.read_text(encoding="utf-8"))
            self.assertEqual(record["event"], "analysis.completed")
            self.assertEqual(record["matched_count"], 1)
            self.assertEqual(record["event_count"], 2)

    async def test_emits_analysis_failure_without_completed_update(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            event_log_path = directory / "session.jsonl"
            pcap_path = directory / "capture.pcap"
            report_path = directory / "correlation.json"
            runtime = LiveRuntime()
            runtime._event_logger = EventLogger(event_log_path)

            with patch(
                "bluetooth_sniffer.display.live_runtime.analyze_session",
                new=AsyncMock(side_effect=ValueError("no decoded ATT traffic")),
            ):
                await runtime._analyze_completed_session(
                    event_log_path,
                    pcap_path,
                    report_path,
                )

            updates = runtime.drain_updates()
            self.assertEqual(len(updates), 1)
            self.assertEqual(
                updates[0],
                RuntimeFailed(
                    operation="analysis",
                    error_type="ValueError",
                    message="no decoded ATT traffic",
                ),
            )

            record = json.loads(event_log_path.read_text(encoding="utf-8"))
            self.assertEqual(record["event"], "analysis.failed")
            self.assertEqual(record["error_type"], "ValueError")
            self.assertEqual(
                record["error_message"],
                "no decoded ATT traffic",
            )


if __name__ == "__main__":
    unittest.main()
