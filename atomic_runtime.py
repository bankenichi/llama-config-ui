"""Atomic launcher integration and versioned profile storage.

The C++ runtime remains authoritative for inference behavior. This module talks to
the tracked PowerShell launcher through JSON and never reconstructs a shell command,
which keeps Windows paths and user-supplied values as literal argv entries.
"""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen


SCHEMA_VERSION = 1


class AtomicLauncherError(RuntimeError):
    """Raised when the canonical launcher cannot complete an operation."""


def infer_atomic_root(ui_dir: Path) -> Path:
    """Return the Atomic worktree containing ``tools/llama-config-ui``."""

    ui_dir = Path(ui_dir)
    if ui_dir.parent.name.lower() == "tools":
        return ui_dir.parent.parent
    return Path(os.environ.get("ATOMIC_LLAMA_ROOT", ui_dir.parent))


def _powershell_path() -> Path:
    selected = os.environ.get("ATOMIC_POWERSHELL")
    if selected:
        return Path(selected)
    found = shutil.which("pwsh") or shutil.which("powershell")
    if not found:
        raise AtomicLauncherError("Neither pwsh nor Windows PowerShell is available.")
    return Path(found)


class AtomicLauncher:
    """Typed adapter for ``scripts/atomic-launcher.ps1``."""

    def __init__(
        self,
        atomic_root: Path,
        powershell: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.atomic_root = Path(atomic_root)
        self.launcher_path = self.atomic_root / "scripts" / "atomic-launcher.ps1"
        self.powershell = Path(powershell) if powershell else _powershell_path()
        self.runner = runner or subprocess.run

    def command(
        self,
        action: str,
        stack: str,
        preset: str,
        config_path: Path | None = None,
    ) -> list[str]:
        command = [
            str(self.powershell),
            "-NoProfile",
            "-File",
            str(self.launcher_path),
            "-Action",
            action,
            "-Stack",
            stack,
            "-Preset",
            preset,
        ]
        if config_path is not None:
            command.extend(["-ConfigPath", str(config_path)])
        if action != "Launch":
            command.append("-Json")
        return command

    def invoke(
        self,
        action: str,
        stack: str,
        preset: str,
        config: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        config_path: Path | None = None
        try:
            if config is not None:
                handle = tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=".json",
                    prefix="atomic-ui-",
                    delete=False,
                )
                with handle:
                    json.dump(config, handle, ensure_ascii=False, indent=2)
                config_path = Path(handle.name)

            result = self.runner(
                self.command(action, stack, preset, config_path),
                cwd=self.atomic_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "launcher failed").strip()
                raise AtomicLauncherError(detail)
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise AtomicLauncherError(
                    f"Atomic launcher returned invalid JSON: {exc}: {result.stdout[:500]}"
                ) from exc
        finally:
            if config_path is not None:
                config_path.unlink(missing_ok=True)


def _coerce_legacy_value(key: str, value: Any) -> Any:
    integer_keys = {
        "port",
        "ctx_size",
        "gpu_layers",
        "draft_gpu_layers",
        "n_cpu_moe",
        "spec_draft_n_max",
        "spec_draft_n_min",
        "batch_size",
        "ubatch_size",
    }
    boolean_keys = {
        "context_shift",
        "metrics",
        "vision_enabled",
        "spec_enabled",
        "prefetch_experts",
        "pin_host",
    }
    if key in integer_keys and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if key in boolean_keys and isinstance(value, str):
        if value.lower() in {"true", "on", "1"}:
            return True
        if value.lower() in {"false", "off", "0"}:
            return False
    return value


def _infer_legacy_stack(name: str, args: dict[str, Any]) -> str:
    lowered = name.lower()
    model = str(args.get("model", "")).lower()
    spec_type = str(args.get("spec-type", "")).lower()
    draft = args.get("spec-draft-model") or args.get("model-draft")
    if "ternary" in lowered or "bonsai" in lowered or "ternary" in model or spec_type in {"dspark", "draft-dspark"}:
        return "ternary"
    if "qwen" in lowered or "qwen" in model or (spec_type in {"mtp", "nextn", "draft-mtp"} and not draft):
        return "qwen"
    if "12b" in lowered or "12b" in model:
        return "gemma12"
    return "gemma26"


def migrate_legacy_profiles(source: Path) -> dict[str, Any]:
    """Read old flag dictionaries without modifying their source file."""

    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    key_map = {
        "model": "model",
        "mmproj": "mmproj",
        "spec-draft-model": "draft_model",
        "model-draft": "draft_model",
        "cache-type-k": "cache_type_k",
        "cache-type-v": "cache_type_v",
        "spec-draft-type-k": "draft_cache_type_k",
        "cache-type-k-draft": "draft_cache_type_k",
        "spec-draft-type-v": "draft_cache_type_v",
        "cache-type-v-draft": "draft_cache_type_v",
        "spec-draft-n-max": "spec_draft_n_max",
        "spec-draft-n-min": "spec_draft_n_min",
        "spec-draft-ngl": "draft_gpu_layers",
        "n-gpu-layers-draft": "draft_gpu_layers",
        "n-gpu-layers": "gpu_layers",
        "n-cpu-moe": "n_cpu_moe",
        "ctx-size": "ctx_size",
        "port": "port",
        "batch-size": "batch_size",
        "ubatch-size": "ubatch_size",
        "context-shift": "context_shift",
        "reasoning": "reasoning",
    }
    migrated: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "profiles": {}}
    for name, legacy_args in raw.items():
        if not isinstance(legacy_args, dict):
            continue
        stack = _infer_legacy_stack(name, legacy_args)
        overrides: dict[str, Any] = {}
        unknown: dict[str, Any] = {}
        for old_key, value in legacy_args.items():
            if old_key == "spec-type":
                current = str(value).lower()
                if current in {"mtp", "nextn"}:
                    value = "draft-mtp"
                elif current == "dspark":
                    value = "draft-dspark"
                overrides["spec_type"] = value
                overrides["spec_enabled"] = value != "none"
                continue
            new_key = key_map.get(old_key)
            if new_key:
                overrides[new_key] = _coerce_legacy_value(new_key, value)
            else:
                unknown[old_key] = value
        profile: dict[str, Any] = {
            "stack": stack,
            "preset": "standard",
            "overrides": overrides,
        }
        if unknown:
            profile["legacy_unknown"] = unknown
        migrated["profiles"][name] = profile
    return migrated


class AtomicProfileStore:
    """Merge immutable starter profiles with mutable local profiles."""

    def __init__(self, defaults_path: Path, user_path: Path) -> None:
        self.defaults_path = Path(defaults_path)
        self.user_path = Path(user_path)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"schema_version": SCHEMA_VERSION, "profiles": {}}
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("profiles"), dict):
            raise ValueError(f"Unsupported Atomic profile schema in {path}")
        return value

    def load(self) -> dict[str, Any]:
        defaults = self._read(self.defaults_path)
        users = self._read(self.user_path)
        profiles: dict[str, Any] = {}
        for name, profile in defaults["profiles"].items():
            profiles[name] = {**profile, "readonly": True}
        for name, profile in users["profiles"].items():
            profiles[name] = {**profile, "readonly": False}
        return {"schema_version": SCHEMA_VERSION, "profiles": profiles}

    def _write_users(self, value: dict[str, Any]) -> None:
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.user_path.with_suffix(self.user_path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.user_path)

    def save(self, name: str, profile: dict[str, Any]) -> None:
        if not name.strip():
            raise ValueError("Profile name is required")
        defaults = self._read(self.defaults_path)
        if name in defaults["profiles"]:
            raise ValueError(f"Starter profile '{name}' is read-only")
        users = self._read(self.user_path)
        users["profiles"][name] = profile
        self._write_users(users)

    def delete(self, name: str) -> None:
        users = self._read(self.user_path)
        if name not in users["profiles"]:
            raise KeyError(name)
        del users["profiles"][name]
        self._write_users(users)

    def import_legacy(self, source: Path) -> dict[str, Any]:
        migrated = migrate_legacy_profiles(source)
        users = self._read(self.user_path)
        if self.user_path.exists():
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.user_path, self.user_path.with_name(f"{self.user_path.name}.{timestamp}.bak"))
        users["profiles"].update(migrated["profiles"])
        self._write_users(users)
        return migrated


class AtomicProcessManager:
    """Own one Atomic llama-server child and its diagnostics.

    Validation always happens before process creation. The active configuration is
    persisted so a UI restart can report what was launched, while process control
    remains limited to the exact recorded PID.
    """

    def __init__(
        self,
        launcher: AtomicLauncher,
        state_dir: Path,
        popen_factory: Callable[..., subprocess.Popen[str]] | None = None,
    ) -> None:
        self.launcher = launcher
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.popen_factory = popen_factory or subprocess.Popen
        self.config_path = self.state_dir / "atomic-active-config.json"
        self.pid_path = self.state_dir / "atomic-server.pid"
        self.log_path = self.state_dir / "atomic-server.log"
        self.diagnostics_path = self.state_dir / "atomic-diagnostics.json"
        self._process: subprocess.Popen[str] | None = None
        self._log_handle: Any = None
        self._last_preview: dict[str, Any] | None = None

    @staticmethod
    def _pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, PermissionError):
            return False

    @staticmethod
    def _process_start_marker(pid: int) -> str | None:
        """Return an OS process-creation identity suitable for PID recovery.

        PIDs are reusable, so a persisted PID by itself is not sufficient authority
        to stop a process after the UI restarts. Windows is the owner platform; the
        Linux marker keeps development and tests safe where ``/proc`` is available.
        """

        if pid <= 0:
            return None
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                process_query_limited_information = 0x1000
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.GetProcessTimes.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(wintypes.FILETIME),
                    ctypes.POINTER(wintypes.FILETIME),
                    ctypes.POINTER(wintypes.FILETIME),
                    ctypes.POINTER(wintypes.FILETIME),
                ]
                kernel32.GetProcessTimes.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
                if not handle:
                    return None
                try:
                    created = wintypes.FILETIME()
                    exited = wintypes.FILETIME()
                    kernel = wintypes.FILETIME()
                    user = wintypes.FILETIME()
                    if not kernel32.GetProcessTimes(
                        handle,
                        ctypes.byref(created),
                        ctypes.byref(exited),
                        ctypes.byref(kernel),
                        ctypes.byref(user),
                    ):
                        return None
                    value = (created.dwHighDateTime << 32) | created.dwLowDateTime
                    return f"windows-filetime:{value}"
                finally:
                    kernel32.CloseHandle(handle)
            except (AttributeError, OSError, ValueError):
                return None

        stat_path = Path("/proc") / str(pid) / "stat"
        try:
            stat = stat_path.read_text(encoding="ascii")
            # The command name is parenthesized and may contain spaces. Fields after
            # the final ')' begin at field 3; field 22 is the kernel start tick.
            fields_after_name = stat[stat.rfind(")") + 2 :].split()
            return f"linux-proc-start:{fields_after_name[19]}"
        except (OSError, IndexError):
            return None

    def _write_pid_record(self, pid: int) -> dict[str, Any]:
        record = {
            "schema_version": SCHEMA_VERSION,
            "pid": pid,
            "process_start_marker": self._process_start_marker(pid),
        }
        temporary = self.pid_path.with_suffix(".pid.tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.pid_path)
        return record

    def _read_pid_record(self) -> dict[str, Any] | None:
        try:
            record = json.loads(self.pid_path.read_text(encoding="utf-8"))
            pid = int(record.get("pid", 0))
        except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
            return None
        marker = record.get("process_start_marker")
        if record.get("schema_version") != SCHEMA_VERSION or pid <= 0 or not isinstance(marker, str):
            return None
        return {"pid": pid, "process_start_marker": marker}

    def _recovered_pid_running(self, record: dict[str, Any]) -> bool:
        pid = int(record["pid"])
        if not self._pid_running(pid):
            return False
        current_marker = self._process_start_marker(pid)
        return current_marker is not None and current_marker == record["process_start_marker"]

    def _record_diagnostics(self, value: dict[str, Any]) -> None:
        temporary = self.diagnostics_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.diagnostics_path)

    def preview(self, stack: str, preset: str, overrides: dict[str, Any]) -> dict[str, Any]:
        preview = self.launcher.invoke("Preview", stack, preset, config=overrides)
        self._last_preview = preview
        return preview

    def start(self, stack: str, preset: str, overrides: dict[str, Any]) -> dict[str, Any]:
        current = self.status(probe_health=False)
        if current["running"]:
            raise AtomicLauncherError(f"Atomic server is already running as PID {current['pid']}.")

        preview = self.preview(stack, preset, overrides)
        validation = preview.get("validation", {})
        if not validation.get("valid", False):
            details = "; ".join(validation.get("errors", [])) or "unknown validation error"
            raise AtomicLauncherError(f"Atomic launch validation failed: {details}")

        self.config_path.write_text(json.dumps(overrides, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        command = self.launcher.command("Launch", stack, preset, self.config_path)
        self._log_handle = self.log_path.open("a", encoding="utf-8", buffering=1)
        self._log_handle.write(f"\n=== Atomic launch {time.strftime('%Y-%m-%d %H:%M:%S')} {stack}/{preset} ===\n")

        kwargs: dict[str, Any] = {
            "cwd": self.launcher.atomic_root,
            "stdout": self._log_handle,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            self._process = self.popen_factory(command, **kwargs)
            pid_record = self._write_pid_record(self._process.pid)
        except Exception:
            self._process = None
            self.pid_path.unlink(missing_ok=True)
            self._log_handle.close()
            self._log_handle = None
            raise

        diagnostics = {
            "schema_version": SCHEMA_VERSION,
            "started_at": time.time(),
            "stack": stack,
            "preset": preset,
            "pid": self._process.pid,
            "process_start_marker": pid_record["process_start_marker"],
            "preview": preview,
        }
        self._record_diagnostics(diagnostics)
        return {
            "ok": True,
            "pid": self._process.pid,
            "validation": validation,
            "preview": preview,
        }

    def _health(self, host: str, port: int) -> dict[str, Any]:
        try:
            with urlopen(f"http://{host}:{port}/health", timeout=0.25) as response:
                body = response.read().decode("utf-8", errors="replace")
                try:
                    payload: Any = json.loads(body)
                except json.JSONDecodeError:
                    payload = body
                return {"ready": 200 <= response.status < 300, "status": response.status, "payload": payload}
        except (OSError, URLError):
            return {"ready": False, "status": None, "payload": None}

    def status(self, probe_health: bool = True) -> dict[str, Any]:
        pid = 0
        if self._process is not None:
            running = self._process.poll() is None
            pid = self._process.pid
            exit_code = self._process.poll()
        else:
            record = self._read_pid_record()
            pid = int(record["pid"]) if record else 0
            running = bool(record and self._recovered_pid_running(record))
            exit_code = None

        preview = self._last_preview
        if preview is None and self.diagnostics_path.exists():
            try:
                preview = json.loads(self.diagnostics_path.read_text(encoding="utf-8")).get("preview")
            except (OSError, json.JSONDecodeError):
                preview = None

        health = {"ready": False, "status": None, "payload": None}
        if running and probe_health and preview:
            config = preview.get("configuration", {})
            health = self._health(str(config.get("host", "127.0.0.1")), int(config.get("port", 8080)))

        return {
            "running": running,
            "ready": health["ready"],
            "health": health,
            "pid": pid or None,
            "exit_code": exit_code,
            "log_path": str(self.log_path),
            "preview": preview,
        }

    def stop(self, timeout: float = 10.0) -> dict[str, Any]:
        status = self.status(probe_health=False)
        if not status["running"]:
            self.pid_path.unlink(missing_ok=True)
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None
            self._process = None
            return {"stopped": True, "was_running": False, "pid": status["pid"]}

        pid = int(status["pid"])
        forced = False
        if self._process is not None and self._process.poll() is None:
            try:
                graceful_signal = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
                self._process.send_signal(graceful_signal)
                self._process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, OSError):
                forced = True
                self._process.terminate()
                try:
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        elif os.name == "nt":
            forced = True
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)

        self.pid_path.unlink(missing_ok=True)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        # A stopped child is no longer the manager's active process. Keeping the
        # completed Popen object here makes later status calls report its stale PID
        # even though the ownership file has been removed, which is especially
        # confusing after Windows has required the force-stop fallback.
        self._process = None
        return {"stopped": True, "was_running": True, "pid": pid, "forced": forced}

    def logs(self, lines: int = 250) -> dict[str, Any]:
        if not self.log_path.exists():
            return {"path": str(self.log_path), "text": ""}
        content = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"path": str(self.log_path), "text": "\n".join(content[-max(1, min(lines, 5000)):])}

    def metrics(self) -> dict[str, Any]:
        status = self.status(probe_health=False)
        preview = status.get("preview") or {}
        config = preview.get("configuration", {})
        if not status["running"] or not config.get("metrics", False):
            return {"available": False, "reason": "metrics are not enabled on a running server"}
        host = str(config.get("host", "127.0.0.1"))
        port = int(config.get("port", 8080))
        try:
            with urlopen(f"http://{host}:{port}/metrics", timeout=0.5) as response:
                return {"available": True, "text": response.read().decode("utf-8", errors="replace")}
        except (OSError, URLError) as exc:
            return {"available": False, "reason": str(exc)}

    def diagnostics(self) -> dict[str, Any]:
        if not self.diagnostics_path.exists():
            return {"available": False}
        value = json.loads(self.diagnostics_path.read_text(encoding="utf-8"))
        value["available"] = True
        value["status"] = self.status()
        value["logs"] = self.logs()
        return value
