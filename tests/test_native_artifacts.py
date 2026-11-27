"""Native container recognition must retain the COM reopen evidence boundary."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from v03_jobs import artifact_rows
from v03_jobs import load_job
from v03_schema import normalize

OLE = bytes.fromhex("d0cf11e0a1b11ae1")
MODERN = bytes.fromhex("0897389c00000004")


class NativeArtifactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, extension="sldprt", header=MODERN):
        path = self.root / ("Probe." + extension.upper())
        path.write_bytes(header + b"fixture payload")
        return path

    def proof(self, path, **changes):
        opened = {"path": str(path), "ok": True, "errors": 0}
        report = {"status": "PASS", "revision": "34.0.0", "nativeOpen": opened}
        report.update(changes)
        (self.root / "native.json").write_text(json.dumps(report), encoding="utf-8")

    def artifacts(self, extension="sldprt", dependencies=None):
        job = {"document_type": "part", "dependencies": dependencies or [],
               "outputs": {"name": "Probe", "formats": [extension]}}
        return artifact_rows(job, self.root, self.root)

    def test_legacy_native_formats_need_no_new_evidence(self):
        for extension in ("sldprt", "sldasm", "slddrw"):
            with self.subTest(extension=extension):
                self.write(extension, OLE)
                self.assertEqual(len(self.artifacts(extension)), 1)

    def test_modern_prefix_varies_and_native_formats_share_reopen_check(self):
        for extension in ("sldprt", "sldasm", "slddrw"):
            for prefix in ("8f9e51c7", "0897389c", "d77b9568"):
                with self.subTest(extension=extension, prefix=prefix):
                    path = self.write(extension, bytes.fromhex(prefix + "00000004"))
                    self.proof(path)
                    self.assertEqual(len(self.artifacts(extension)), 1)

    def test_modern_header_without_evidence_is_rejected(self):
        self.write()
        with self.assertRaises(ValueError):
            self.artifacts()

    def test_failed_or_legacy_host_evidence_is_rejected(self):
        path = self.write()
        for changes in ({"status": "FAIL"}, {"revision": "22.0.0"}, {"revision": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.proof(path, **changes)
                self.artifacts()

    def test_matching_successful_open_is_required(self):
        path = self.write()
        for changes in ({"path": str(self.root / "Other.SLDPRT")}, {"ok": False},
                        {"errors": 1}, {"path": None}, {"path": []}, {"path": ""}):
            opened = {"path": str(path), "ok": True, "errors": 0, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.proof(path, nativeOpen=opened)
                self.artifacts()

    def test_non_object_open_records_are_rejected(self):
        path = self.write()
        for opened in (None, [], "PASS"):
            with self.subTest(opened=opened), self.assertRaises(ValueError):
                self.proof(path, nativeOpen=opened)
                self.artifacts()

    def test_invalid_evidence_documents_fail_as_validation_errors(self):
        self.write()
        for payload in ("[]", "null", "{", '{"status":"PASS","status":"FAIL"}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                (self.root / "native.json").write_text(payload, encoding="utf-8")
                self.artifacts()

    def test_wrong_container_marker_is_rejected_even_with_evidence(self):
        path = self.write(header=bytes.fromhex("0897389c00000005"))
        self.proof(path)
        with self.assertRaises(ValueError):
            self.artifacts()

    def test_staged_native_dependencies_use_their_source_open_record(self):
        self.write(header=OLE)
        references = self.root / "references"
        references.mkdir()
        dependency = references / "Pin.SLDPRT"
        dependency.write_bytes(MODERN + b"dependency fixture")
        self.proof(dependency, nativeOpen=None, **{
            "sourceOpen:Pin": {"path": str(dependency), "ok": True, "errors": 0}})
        rows = self.artifacts(dependencies=[{"id": "Pin", "path": "input.SLDPRT"}])
        self.assertEqual([row["path"] for row in rows], ["Probe.SLDPRT", "references/Pin.SLDPRT"])

    def test_unrelated_report_fields_do_not_prove_a_native_open(self):
        path = self.write()
        self.proof(path, nativeOpen=None, randomOpen={"path": str(path), "ok": True, "errors": 0})
        with self.assertRaises(ValueError):
            self.artifacts()

    def test_existing_interchange_signatures_remain_supported(self):
        for extension, header in (("step", b"ISO-10303-21;"), ("pdf", b"%PDF-"), ("dwg", b"AC10")):
            with self.subTest(extension=extension):
                self.write(extension, header)
                self.assertEqual(len(self.artifacts(extension)), 1)

    def test_dxf_validation_still_requires_a_complete_document(self):
        cases = ((b"AutoCAD Binary DXFfixture", True),
                 (b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF", True),
                 (b"0\nSECTION\n", False), (b"not a DXF", False))
        for payload, valid in cases:
            with self.subTest(payload=payload):
                (self.root / "Probe.DXF").write_bytes(payload)
                if valid:
                    self.assertEqual(len(self.artifacts("dxf")), 1)
                else:
                    with self.assertRaises(ValueError):
                        self.artifacts("dxf")

    def test_arbitrary_bytes_are_rejected(self):
        self.write(header=b"not a native document")
        with self.assertRaises(ValueError):
            self.artifacts()

    def test_tapered_link_regression_fixture_uses_the_standard_schema(self):
        fixture = Path(__file__).parent / "fixtures" / "sw2026_tapered_link.json"
        job = normalize(load_job(fixture), self.root)
        self.assertEqual(job["document_type"], "part")
        self.assertEqual(len(job["features"]), 5)
        self.assertAlmostEqual(job["validation"]["volume_mm3"], 2210063.9753196533)
        self.assertEqual(job["validation"]["bounds_mm"], [[-55, -55, 0], [360, 55, 120]])


if __name__ == "__main__":
    unittest.main()
