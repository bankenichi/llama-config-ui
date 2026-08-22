import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from atomic_runtime import (
    AtomicLauncher,
    AtomicLauncherError,
    AtomicProcessManager,
    AtomicProfileStore,
    infer_atomic_root,
    migrate_legacy_profiles,
)


class AtomicRootTests(unittest.TestCase):
    def test_infers_atomic_root_from_tools_submodule(self):
        ui_dir = Path(r"C:\repo\atomic\tools\llama-config-ui")
        self.assertEqual(infer_atomic_root(ui_dir), Path(r"C:\repo\atomic"))


class AtomicLauncherTests(unittest.TestCase):
    def test_builds_literal_argument_vector_for_paths_with_spaces(self):
        launcher = AtomicLauncher(
            atomic_root=Path(r"C:\Users\Owner\Documents\atomic repo"),
            powershell=Path(r"C:\Program Files\PowerShell\7\pwsh.exe"),
        )
        command = launcher.command(
            action="Preview",
            stack="ternary",
            preset="standard",
            config_path=Path(r"C:\Temp Folder\atomic config.json"),
        )
        self.assertEqual(command[0], r"C:\Program Files\PowerShell\7\pwsh.exe")
        self.assertIn(r"C:\Temp Folder\atomic config.json", command)
        self.assertNotIn('"C:\\Temp Folder\\atomic config.json"', command)

    def test_parses_launcher_json_and_reports_stderr(self):
        class Result:
            returncode = 0
            stdout = '{"validation":{"valid":true}}'
            stderr = ""

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Result()

        launcher = AtomicLauncher(Path(r"C:\repo\atomic"), runner=runner)
        value = launcher.invoke("Describe", "ternary", "standard")
        self.assertTrue(value["validation"]["valid"])
        self.assertEqual(calls[0][0][0], str(launcher.powershell))

        class Failure:
            returncode = 1
            stdout = ""
            stderr = "preflight failed"

        launcher.runner = lambda *args, **kwargs: Failure()
        with self.assertRaisesRegex(AtomicLauncherError, "preflight failed"):
            launcher.invoke("Preview", "ternary", "standard")


class AtomicProfileTests(unittest.TestCase):
    def test_shipped_profiles_include_validated_ternary_context_tiers(self):
        defaults = Path(__file__).resolve().parents[1] / "atomic-profiles.defaults.json"
        profiles = json.loads(defaults.read_text(encoding="utf-8"))["profiles"]
        self.assertEqual(profiles["Ternary DSpark + Vision"]["preset"], "standard")
        self.assertEqual(profiles["Ternary 64K DSpark + Vision"]["preset"], "64k")
        self.assertEqual(profiles["Ternary 128K DSpark + Vision"]["preset"], "128k")

    def test_store_separates_starter_and_user_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = root / "defaults.json"
            users = root / "users.json"
            defaults.write_text(json.dumps({
                "schema_version": 1,
                "profiles": {"Starter": {"stack": "ternary", "preset": "standard", "overrides": {}}},
            }), encoding="utf-8")
            store = AtomicProfileStore(defaults, users)
            store.save("Mine", {"stack": "qwen", "preset": "standard", "overrides": {"port": 9000}})
            combined = store.load()
            self.assertTrue(combined["profiles"]["Starter"]["readonly"])
            self.assertFalse(combined["profiles"]["Mine"]["readonly"])
            self.assertNotIn("Mine", json.loads(defaults.read_text(encoding="utf-8"))["profiles"])

    def test_legacy_import_is_non_destructive_and_preserves_unknowns(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "profiles.json"
            source.write_text(json.dumps({
                "Qwen daily": {
                    "model": r"C:\Program Files\llamacpp\qwen.gguf",
                    "spec-type": "mtp",
                    "cache-type-k": "turbo4",
                    "cache-type-v": "turbo3",
                    "n-cpu-moe": "28",
                    "custom-new-flag": "kept",
                },
                "Gemma MTP": {
                    "model": r"C:\Program Files\llamacpp\gemma.gguf",
                    "spec-type": "mtp",
                    "spec-draft-model": r"C:\Program Files\llamacpp\assistant.gguf",
                },
            }), encoding="utf-8")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            migrated = migrate_legacy_profiles(source)
            after = hashlib.sha256(source.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertEqual(migrated["profiles"]["Qwen daily"]["stack"], "qwen")
            self.assertEqual(migrated["profiles"]["Qwen daily"]["overrides"]["spec_type"], "draft-mtp")
            self.assertEqual(migrated["profiles"]["Qwen daily"]["legacy_unknown"]["custom-new-flag"], "kept")
            self.assertEqual(migrated["profiles"]["Gemma MTP"]["stack"], "gemma26")
            self.assertEqual(
                migrated["profiles"]["Gemma MTP"]["overrides"]["draft_model"],
                r"C:\Program Files\llamacpp\assistant.gguf",
            )


class AtomicProcessManagerTests(unittest.TestCase):
    def test_validates_before_launch_and_tracks_process_lifecycle(self):
        class Launcher:
            atomic_root = Path(r"C:\repo\atomic")

            def invoke(self, action, stack, preset, config=None, timeout=30):
                self.last = (action, stack, preset, config)
                return {
                    "validation": {"valid": True, "errors": [], "warnings": ["media fallback"]},
                    "configuration": {"host": "127.0.0.1", "port": 8081},
                    "redacted_arguments": ["--model", "model.gguf"],
                    "environment": {},
                }

            def command(self, action, stack, preset, config_path=None):
                return ["pwsh", "-File", "launcher.ps1", "-Action", action, "-ConfigPath", str(config_path)]

        class Process:
            pid = 4321

            def __init__(self):
                self.returncode = None
                self.signals = []

            def poll(self):
                return self.returncode

            def send_signal(self, value):
                self.signals.append(value)
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -9

        process = Process()
        calls = []

        def popen(command, **kwargs):
            calls.append((command, kwargs))
            return process

        with tempfile.TemporaryDirectory() as directory:
            manager = AtomicProcessManager(Launcher(), Path(directory), popen_factory=popen)
            started = manager.start("ternary", "standard", {"port": 8081})
            self.assertEqual(started["pid"], 4321)
            self.assertTrue(manager.status()["running"])
            self.assertTrue(Path(directory, "atomic-active-config.json").exists())
            pid_record = json.loads(Path(directory, "atomic-server.pid").read_text(encoding="utf-8"))
            self.assertEqual(pid_record["pid"], 4321)
            self.assertIn("process_start_marker", pid_record)
            self.assertEqual(calls[0][0][0], "pwsh")
            stopped = manager.stop(timeout=0.1)
            self.assertTrue(stopped["stopped"])
            self.assertFalse(Path(directory, "atomic-server.pid").exists())
            status = manager.status(probe_health=False)
            self.assertFalse(status["running"])
            self.assertIsNone(status["pid"])
            self.assertIsNone(status["exit_code"])

    def test_recovered_pid_requires_matching_process_creation_marker(self):
        class Launcher:
            atomic_root = Path(r"C:\repo\atomic")

        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory, "atomic-server.pid")
            pid_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pid": 4321,
                        "process_start_marker": "windows-filetime:100",
                    }
                ),
                encoding="utf-8",
            )
            manager = AtomicProcessManager(Launcher(), Path(directory))
            manager._pid_running = lambda pid: True
            manager._process_start_marker = lambda pid: "windows-filetime:100"
            self.assertTrue(manager.status(probe_health=False)["running"])

            manager._process_start_marker = lambda pid: "windows-filetime:200"
            stale = manager.status(probe_health=False)
            self.assertFalse(stale["running"])
            self.assertEqual(stale["pid"], 4321)
            stopped = manager.stop(timeout=0)
            self.assertFalse(stopped["was_running"])
            self.assertFalse(pid_path.exists())

    def test_launch_failure_closes_log_and_removes_pid_record(self):
        class Launcher:
            atomic_root = Path(r"C:\repo\atomic")

            def invoke(self, *args, **kwargs):
                return {
                    "validation": {"valid": True, "errors": [], "warnings": []},
                    "configuration": {"host": "127.0.0.1", "port": 8081},
                }

            def command(self, *args, **kwargs):
                return ["pwsh", "launcher.ps1"]

        with tempfile.TemporaryDirectory() as directory:
            manager = AtomicProcessManager(
                Launcher(),
                Path(directory),
                popen_factory=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("spawn failed")),
            )
            with self.assertRaisesRegex(OSError, "spawn failed"):
                manager.start("ternary", "standard", {})
            self.assertIsNone(manager._log_handle)
            self.assertFalse(Path(directory, "atomic-server.pid").exists())

    def test_rejects_invalid_preview_without_starting(self):
        class Launcher:
            atomic_root = Path(r"C:\repo\atomic")

            def invoke(self, *args, **kwargs):
                return {"validation": {"valid": False, "errors": ["bad DSpark sidecar"], "warnings": []}}

        with tempfile.TemporaryDirectory() as directory:
            manager = AtomicProcessManager(Launcher(), Path(directory), popen_factory=lambda *a, **k: self.fail("spawned"))
            with self.assertRaisesRegex(AtomicLauncherError, "bad DSpark sidecar"):
                manager.start("ternary", "standard", {})


if __name__ == "__main__":
    unittest.main()
