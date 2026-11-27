import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sw_supervisor import bounded_worker, inspect, supervise
from sw_supervisor_state import OUTPUT, atomic, classify, exclusive, read


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        self.space = tempfile.TemporaryDirectory(dir=OUTPUT)
        self.addCleanup(self.space.cleanup)
        self.run = Path(self.space.name)
        atomic(self.run / "BASELINE.json", {"started": datetime.now().astimezone().isoformat()})
        self.plan = {"job": {"document_type": "part"}, "host_revision": "22.0.0", "outputs": ["part.SLDPRT"]}
        self.host = lambda: {"status": "PASS", "pid": 12345, "revision": "22.0.0", "documents": 0}
        self.noevents = lambda: []

    def pass_worker(self, folder, _kind, host, _timeout, progress):
        progress(stage="reopen", heartbeat="mock")
        (folder / "part.SLDPRT").write_bytes(b"mock")
        atomic(folder / "native.json", dict(status="PASS", stage="complete", pid=host["pid"],
               revision=host["revision"], documentCountAfter=0, preferencesRestored=True,
               nativeSave={"ok": True}, nativeOpen={"ok": True}, reopenedGeometry={"verified": True}))
        return 0, False

    def test_resume_and_cache_verify_bytes(self):
        self.assertEqual(supervise(self.run, "smoke", self.plan, self.host, self.pass_worker)["status"], "verified")
        self.assertTrue(inspect(self.run / "smoke")["hashes_match"])
        result = supervise(self.run, "smoke", self.plan, self.host, lambda *a: self.fail("cache missed"))
        self.assertEqual(result["attempt"], 1)
        with self.assertRaises(ValueError):
            supervise(self.run, "smoke", {**self.plan, "changed": True}, self.host, self.pass_worker)
        (self.run / "smoke" / "verified" / "part.SLDPRT").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            supervise(self.run, "smoke", self.plan, self.host, self.pass_worker)

    def test_rpc_busy_retries_once_and_preserves_partial(self):
        observed = []
        def worker(folder, kind, host, timeout, progress):
            observed.append(folder)
            if len(observed) == 1:
                atomic(folder / "native.json", {"status": "BLOCKED", "stage": "attach", "hresult": "0x80010001"})
                return 1, False
            return self.pass_worker(folder, kind, host, timeout, progress)
        result = supervise(self.run, "smoke", self.plan, self.host, worker)
        self.assertEqual(result["status"], "verified")
        self.assertTrue((observed[0] / "native.json").is_file())
        self.assertEqual(read(self.run / "resource.json")["retries"], 1)

    def test_publication_recovers_after_atomic_rename(self):
        supervise(self.run, "smoke", self.plan, self.host, self.pass_worker)
        phase = self.run / "smoke"
        state = read(phase / "job_state.json")
        state["status"] = "checkpointed"
        atomic(phase / "job_state.json", state)
        result = supervise(self.run, "smoke", self.plan, lambda: self.fail("unexpected native probe"),
                           lambda *a: self.fail("unexpected launch"))
        self.assertEqual(result["stage"], "published_after_interruption")
        self.assertTrue(inspect(phase)["hashes_match"])

    def test_timeout_and_circuit_breaker_do_not_control_shared_host(self):
        def fail(*_):
            return 1, True
        result = supervise(self.run, "smoke", self.plan, self.host, fail, self.noevents)
        self.assertFalse(result["host_owned"])
        self.assertEqual(result["reason"], "host_timeout")
        blocked = supervise(self.run, "smoke", self.plan, self.host, lambda *a: self.fail("unsafe retry"))
        self.assertEqual(blocked["stage"], "host_precondition")
        new_host = lambda: {**self.host(), "pid": 23456}
        supervise(self.run, "explode-capture", self.plan, new_host, fail, self.noevents)
        cut = supervise(self.run, "regression", self.plan, new_host, lambda *a: self.fail("circuit breaker"))
        self.assertEqual(cut["stage"], "budget_or_circuit_breaker")
        self.assertEqual(read(self.run / "resource.json")["restarts"], 0)

    def test_user_documents_and_global_lock(self):
        user = lambda: {**self.host(), "documents": 1}
        result = supervise(self.run, "smoke", self.plan, user, lambda *a: self.fail("user document touched"))
        self.assertEqual(result["status"], "blocked")
        with exclusive(OUTPUT / ".launch.lock"):
            with self.assertRaises(BlockingIOError):
                supervise(self.run, "smoke", self.plan, self.host, self.pass_worker)

    def test_isolated_child_timeout_and_exit(self):
        log_folder = self.run / "child"
        log_folder.mkdir()
        result = bounded_worker([sys.executable, "-c", "import time; time.sleep(5)"],
                                log_folder, .25, lambda **_: None)
        self.assertTrue(result[1])
        next_folder = self.run / "exit"
        next_folder.mkdir()
        result = bounded_worker([sys.executable, "-c", "raise SystemExit(17)"],
                                next_folder, 3, lambda **_: None)
        self.assertEqual(result, (17, False))
        self.assertEqual(classify(0, {"status": "FAIL", "hresult": "0x80070057"}), ("failed", "model_or_api"))


if __name__ == "__main__":
    unittest.main()

