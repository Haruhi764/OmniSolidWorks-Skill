import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from v03_jobs import OLE_HEADER, verify_native_output


def cfb_header():
    data = bytearray(2048)
    data[:8] = OLE_HEADER
    data[26:34] = b"\x03\x00\xfe\xff\x09\x00\x06\x00"
    return data


class NativeContainerTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.space = TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.space.cleanup)

    def sample(self, suffix=".SLDPRT", kind=1, body=None, revision="34.0.0"):
        path = Path(self.space.name) / ("Artifact" + suffix)
        if body is None:
            body = b"synthetic unknown container" * 30
        path.write_bytes(body)
        proof = {"name": path.name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                 "documentType": kind}
        opened = {"path": str(path), "ok": True, "errors": 0, "warnings": 0, "documentType": kind,
                  "fileBeforeReopen": proof.copy()}
        saved = {"path": str(path), "ok": True, "errors": 0, "warnings": 0}
        report = {"nativeOpen": opened, "nativeSave": saved, "nativeFile": proof, "revision": revision,
                  "status": "PASS", "stage": "complete", "documentCountBefore": 0, "documentCountAfter": 0,
                  "preferencesRestored": True, "reopenedGeometry": {"verified": True, "solids": 1, "bodyCheckCode": 0},
                  "reopenedAssembly": {"verified": True, "components": [{}]},
                  "reopenedDrawing": {"verified": True, "views": [{}]}}
        return path, report

    def verify(self, path, report):
        data = path.read_bytes()
        return verify_native_output(path, report, len(data), hashlib.sha256(data).hexdigest())

    def test_2014_compound_file_still_requires_native_evidence(self):
        path, report = self.sample(body=cfb_header(), revision="22.0.0")
        self.assertEqual(self.verify(path, report), "compound-file")
        report.pop("nativeOpen")
        with self.assertRaisesRegex(ValueError, "reopen"):
            self.verify(path, report)

    def test_2026_unknown_requires_exact_typed_reopen_for_all_native_extensions(self):
        for suffix, kind in ((".SLDPRT", 1), (".SLDASM", 2), (".SLDDRW", 3)):
            with self.subTest(kind=kind):
                path, report = self.sample(suffix, kind)
                self.assertEqual(self.verify(path, report), "native-reopen")
                report["nativeOpen"]["documentType"] = (kind % 3) + 1
                with self.assertRaisesRegex(ValueError, "reopen"):
                    self.verify(path, report)

    def test_rejects_unknown_format_on_older_hosts(self):
        for revision in ("22.0.0", "32.0.0", "invalid"):
            with self.subTest(revision=revision):
                path, report = self.sample(revision=revision)
                with self.assertRaisesRegex(ValueError, "signature"):
                    self.verify(path, report)

    def test_rejects_missing_evidence_corrupt_geometry_and_failed_open(self):
        for key, field, value in (("reopenedGeometry", "bodyCheckCode", 6), ("reopenedGeometry", "solids", 0),
                                  ("reopenedGeometry", "verified", False), ("nativeOpen", "errors", 1),
                                  ("nativeOpen", "path", ""), ("nativeSave", "warnings", 4),
                                  ("reopenedAssembly", "components", []), ("reopenedDrawing", "views", [])):
            with self.subTest(key=key, field=field):
                kind, suffix = {"reopenedAssembly": (2, ".SLDASM"),
                                "reopenedDrawing": (3, ".SLDDRW")}.get(key, (1, ".SLDPRT"))
                path, report = self.sample(suffix, kind)
                report[key][field] = value
                with self.assertRaises(ValueError):
                    self.verify(path, report)

    def test_rejects_empty_truncated_ole_fake_extension_and_changed_bytes(self):
        for content in (b"", OLE_HEADER, b"%PDF-1.7\nfake"):
            with self.subTest(content=content):
                path, _ = self.sample(body=content)
                with self.assertRaises(ValueError):
                    self.verify(path, {})
        path, report = self.sample(body=cfb_header())
        path.write_bytes(path.read_bytes()[:-8] + b"modified")
        with self.assertRaisesRegex(ValueError, "reopen"):
            self.verify(path, report)


class PythonPreflightTests(unittest.TestCase):
    def test_unsupported_runtimes_stop_before_native_or_schema_imports(self):
        for minor in (10, 11):
            with self.subTest(minor=minor):
                wrapper = """
import builtins, runpy, sys
original_import = builtins.__import__
def forbid_native(name, *args, **kwargs):
    if name in ('winreg', 'msvcrt', 'v03_schema', 'hashlib'):
        raise AssertionError('incompatible runtime reached ' + name)
    return original_import(name, *args, **kwargs)
sys.version_info = (3, int(sys.argv[1]), 0)
builtins.__import__ = forbid_native
sys.argv = [sys.argv[2], '--preflight']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
                result = subprocess.run([sys.executable, "-B", "-c", wrapper, str(minor),
                                         str(ROOT / "scripts" / "v03_jobs.py")], text=True, capture_output=True,
                                        timeout=10)
                self.assertEqual(result.returncode, 1, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual((report["status"], report["stage"]), ("BLOCKED", "python_version"))
                self.assertIn(f"3.{minor}.0", report["error"])
                self.assertIn("3.12", report["error"])


if __name__ == "__main__":
    unittest.main()