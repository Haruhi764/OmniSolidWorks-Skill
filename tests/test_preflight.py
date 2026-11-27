import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v03_jobs


class PreflightTests(unittest.TestCase):
    def test_invalid_major_has_actionable_message(self):
        with patch.dict(os.environ, {"SOLIDWORKS_REVISION_MAJOR": "2014 SP0"}):
            result = v03_jobs.preflight()
        self.assertEqual((result["status"], result["stage"]), ("BLOCKED", "configuration"))
        self.assertIn("SOLIDWORKS_REVISION_MAJOR", result["error"])

    def test_registered_release_fallback_and_ambiguity(self):
        root = Path(__file__).resolve().parents[1]
        available = {"available": True, "executable": str(root / "SLDWORKS.exe")}
        env = {"ProgramData": str(root)}
        with patch.dict(os.environ, env, clear=True), patch.object(v03_jobs, "registration", side_effect=FileNotFoundError), \
                patch.object(v03_jobs, "registered_releases", return_value={32: available}), \
                patch.object(Path, "is_file", return_value=True):
            self.assertEqual(v03_jobs.configuration()[0], 32)
            with patch.object(v03_jobs, "registered_releases", return_value={31: available, 32: available}):
                with self.assertRaisesRegex(ValueError, "31, 32"):
                    v03_jobs.configuration()

    def test_invalid_template_blocks_before_com(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict(os.environ, {"SOLIDWORKS_PART_TEMPLATE": "relative.prtdot", "SOLIDWORKS_TARGET_PID": "0"}), \
                patch.object(v03_jobs, "configuration", return_value=(22, root, root)), \
                patch.object(v03_jobs, "windows_powershell"), patch.object(v03_jobs, "environment") as com:
            result = v03_jobs.preflight()
        com.assert_not_called()
        self.assertEqual(result["stage"], "templates")
        self.assertIn("SOLIDWORKS_PART_TEMPLATE", result["error"])

    def test_busy_session_blocked_and_identity_retained(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict(os.environ, {"SOLIDWORKS_TARGET_PID": "17"}), \
                patch.object(v03_jobs, "configuration", return_value=(22, root, root)), \
                patch.object(v03_jobs, "windows_powershell"), \
                patch.object(v03_jobs, "get_template", side_effect=lambda kind, path: path / kind), \
                patch.object(v03_jobs, "environment", return_value={"status":"PASS", "documents":1,"pid":17}):
            result = v03_jobs.preflight()
        self.assertEqual((result["status"], result["stage"], result["pid"]), ("BLOCKED", "open_documents", 17))


if __name__ == "__main__":
    unittest.main()
