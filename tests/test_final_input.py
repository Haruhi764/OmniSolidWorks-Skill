import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from v03_jobs import MAX_JOB_BYTES, MAX_JOB_DEPTH, decode_document, load_job
from v03_schema import identifier, normalize, output_path


class JobInputTests(unittest.TestCase):
    def test_original_cli_inputs(self):
        root = Path(__file__).resolve().parents[1]
        examples = sorted((root / "examples" / "v03").glob("*.json"))
        self.assertEqual(len(examples), 3)
        for example in examples:
            with self.subTest(job=example.name):
                self.assertEqual(normalize(load_job(example), root)["document_type"], "part")
        benchmark = load_job(root / "examples" / "benchmarks.json")
        self.assertTrue(benchmark)
        self.assertEqual(decode_document(b'\xef\xbb\xbf{"part":"pin"}'), {"part": "pin"})

    def test_reject_ambiguous_or_unbounded_json(self):
        for payload in (b'{"job":{"diameter":3,"diameter":4}}', b'{"v":NaN}',
                        b'{"v":Infinity}', b'{"v":1e500}', b'{"name":"\xff"}',
                        b" " * (MAX_JOB_BYTES + 1), b"[" * 2000 + b"]" * 2000,
                        b"[" * (MAX_JOB_DEPTH + 1) + b"0" + b"]" * (MAX_JOB_DEPTH + 1)):
            with self.subTest(prefix=payload[:42]), self.assertRaises(ValueError):
                decode_document(payload)
        self.assertIsInstance(decode_document(b"[" * MAX_JOB_DEPTH + b"0" + b"]" * MAX_JOB_DEPTH), list)

    def test_windows_paths_and_identifiers(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(output_path(root, "examples/v09_install_smoke.json"),
                         root / "examples" / "v09_install_smoke.json")
        self.assertEqual(identifier("Console"), "Console")
        for name in ("CON", "aux", "COM1", "LPT9"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                identifier(name)
        for relative in ("../SKILL.md", r"C:\SKILL.md", r"\\server\share\SKILL.md",
                         "examples/COM1.sldprt", "examples./v09_install_smoke.json",
                         "examples/v09_install_smoke.json:stream"):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                output_path(root, relative)


if __name__ == "__main__":
    unittest.main()
