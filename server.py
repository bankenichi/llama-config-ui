#!/usr/bin/env python3
"""Llama Server Config UI — HTTP server with API endpoints."""

import json
import os
import re
import socket
import string
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

# ── Paths ──────────────────────────────────────────────────────────────────
# Where the UI files live (this folder)
STATIC_BASE = Path(__file__).resolve().parent

# Where the llama.cpp install is. Resolution order:
#   1. LLAMACPP_ROOT env var (set at machine scope by the Homelab Deploy-Homelab.ps1 script,
#      and the recommended way to override the install location)
#   2. LLAMACPP_DIR env var (legacy name, kept for backward compatibility with older
#      standalone setups; new deployments should use LLAMACPP_ROOT)
#   3. C:\Program Files\llamacpp (hardcoded default — matches the deploy script's default)
LLAMACPP_ROOT = Path(
    os.environ.get("LLAMACPP_ROOT")
    or os.environ.get("LLAMACPP_DIR")
    or r"C:\Program Files\llamacpp"
)

# Treat the llama.cpp dir as BASE for arg-file purposes — that's where the
# binary reads its config from.
BASE = LLAMACPP_ROOT
ARGS_FILE = LLAMACPP_ROOT / "llama-args.txt"
RUN_SCRIPT = LLAMACPP_ROOT / "run-llama.ps1"

# Per-UI state lives alongside the UI files, not in the install dir.
PROFILE_FILE = STATIC_BASE / "profiles.json"
PID_FILE = STATIC_BASE / "server.pid"

# Where opencode opens by default (user's home — adjust if you want it
# scoped to a specific project dir).
OPENCODE_CWD = Path.home()


# ── arg parsing ──────────────────────────────────────────────────────────────

# llama.cpp's short→long aliases. Keep names that exist in the UI's idMap.
SHORT_TO_LONG = {
    "m":   "model",
    "mu":  "model-url",
    "hf":  "hf-repo",
    "hff": "hf-file",
    "c":   "ctx-size",
    "n":   "n-predict",
    "b":   "batch-size",
    "ub":  "ubatch-size",
    "t":   "threads",
    "tb":  "threads-batch",
    "s":   "seed",
    "ngl": "n-gpu-layers",
    "ts":  "tensor-split",
    "mg":  "main-gpu",
    "sm":  "split-mode",
    "p":   "prompt",
    "f":   "file",
    "r":   "reverse-prompt",
    "e":   "escape",
    "i":   "interactive",
    "h":   "help",
    "l":   "logit-bias",
    "fa":  "flash-attn",
    "np":  "parallel",
    "ctk": "cache-type-k",
    "ctv": "cache-type-v",
    "v":   "verbose",
    "lv":  "log-verbosity",
    "j":   "json-schema",
    "jf":  "json-schema-file",
    "td":  "threads-draft",
    "tbd": "threads-batch-draft",
    "cd":  "ctx-size-draft",
    "ngld":"n-gpu-layers-draft",
}


def _canonical(name: str) -> str:
    """Translate short flag aliases to their long form."""
    return SHORT_TO_LONG.get(name, name)


def parse_args_file(path) -> dict:
    """Parse llama-args.txt into a dict of canonical_flag_name -> value.

    Handles:
      * --long value          → {long: value}
      * --long                → {long: True}
      * --no-foo              → {foo: False}    (so UI can uncheck the checkbox)
      * -x value              → {canonical(x): value}
      * -fa / -np multi-char  → {canonical(...): value}
      * negative numbers as values (--keep -1)
    """
    path = Path(path) if not isinstance(path, Path) else path
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8").strip()
    tokens = _tokenize(text)
    result = {}
    i = 0

    def _looks_like_value(tok: str) -> bool:
        """True if `tok` should be consumed as the value for a preceding flag."""
        if not tok:
            return False
        if not tok.startswith("-"):
            return True
        # negative numbers like -1, -0.5 are values, not flags
        rest = tok[1:]
        if rest and rest[0] == "-":
            rest = rest[1:]
        try:
            float(rest)
            return True
        except ValueError:
            return False

    while i < len(tokens):
        tok = tokens[i]

        if tok.startswith("--"):
            name = tok[2:]
            # --no-X → store X=False (lets UI uncheck a checkbox)
            if name.startswith("no-"):
                result[_canonical(name[3:])] = False
                i += 1
                continue
            name = _canonical(name)
            if i + 1 < len(tokens) and _looks_like_value(tokens[i + 1]):
                result[name] = tokens[i + 1]
                i += 2
            else:
                result[name] = True
                i += 1

        elif tok.startswith("-") and len(tok) >= 2 and not _looks_like_value(tok):
            name = _canonical(tok[1:])
            if i + 1 < len(tokens) and _looks_like_value(tokens[i + 1]):
                result[name] = tokens[i + 1]
                i += 2
            else:
                result[name] = True
                i += 1
        else:
            # stray value with no preceding flag — skip
            i += 1

    return result


def _tokenize(text: str):
    """Split on whitespace but respect quoted strings."""
    tokens = []
    i = 0
    while i < len(text):
        if text[i] in " \t\n\r":
            i += 1
            continue
        if text[i] == '"':
            end = text.index('"', i + 1)
            tokens.append(text[i + 1:end])
            i = end + 1
        else:
            end = i
            while end < len(text) and text[end] not in " \t\n\r\"":
                end += 1
            tokens.append(text[i:end])
            i = end
    return tokens


def build_args_line(args: dict) -> str:
    """Rebuild command-line args from a parsed dict.

    Values:
      True       → emit --name
      False      → emit --no-name  (negation)
      "" / None  → skip
      other      → emit --name value  (quoted if it contains spaces)
    """
    parts = []
    for name, value in sorted(args.items()):
        if value is True:
            parts.append(f"--{name}")
        elif value is False:
            parts.append(f"--no-{name}")
        elif value is None or value == "":
            continue
        else:
            val = str(value)
            if " " in val:
                parts.append(f'--{name} "{val}"')
            else:
                parts.append(f"--{name} {val}")
    return " ".join(parts)


# ── profile helpers ──────────────────────────────────────────────────────────

def load_profiles() -> dict:
    if not PROFILE_FILE.exists():
        return {}
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))


def save_profiles(profiles: dict):
    PROFILE_FILE.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")


# ── process management ───────────────────────────────────────────────────────

# Windows CreateProcess flag — gives the child its own console window
# so the user sees the llama-server / opencode output instead of having
# the process run invisibly in the background.
CREATE_NEW_CONSOLE = 0x00000010


def _spawn_in_new_console(cmd, cwd=None, title=None):
    """Spawn `cmd` in a brand-new visible console window on Windows."""
    if os.name == "nt":
        # Do NOT use 'cmd /c start'. CREATE_NEW_CONSOLE natively opens a new 
        # terminal window and preserves the true PID of the child process.
        return subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            creationflags=CREATE_NEW_CONSOLE,
        )
    return subprocess.Popen(cmd, cwd=str(cwd) if cwd else None)


def start_server():
    """Launch run-llama.ps1 in its own visible console window."""
    if not RUN_SCRIPT.exists():
        raise FileNotFoundError(f"run-llama.ps1 not found at {RUN_SCRIPT}")

    cmd = ["powershell.exe", "-NoExit", "-NoProfile",
           "-ExecutionPolicy", "Bypass", "-File", str(RUN_SCRIPT)]
    proc = _spawn_in_new_console(cmd, cwd=LLAMACPP_ROOT, title="llama-server")
    PID_FILE.write_text(str(proc.pid))
    return proc.pid


def stop_server():
    """Kill the recorded PID and the entire process tree below it
    (powershell + the llama-server child it spawned)."""
    if not PID_FILE.exists():
        return False
    pid = PID_FILE.read_text().strip()
    if not pid:
        return False
    try:
        # /T kills the whole tree so the powershell launcher AND llama-server die
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], check=False)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)
    return True


def launch_opencode():
    """Open a new terminal window running `opencode` in the user's home."""
    cmd = ["cmd", "/k", "opencode"]
    _spawn_in_new_console(cmd, cwd=OPENCODE_CWD, title="opencode")
    return True


# ── readiness probe ─────────────────────────────────────────────────────────

def _parse_port_from_args(default=8080):
    """Pluck --port from llama-args.txt so /api/status can probe it."""
    try:
        args = parse_args_file(ARGS_FILE)
        return int(args.get("port", default))
    except Exception:
        return default


def llama_server_ready(host="127.0.0.1", timeout=0.25) -> bool:
    """True if something is accepting TCP on the llama-server port."""
    port = _parse_port_from_args()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ── model & folder discovery ────────────────────────────────────────────────

def discover_models(directory: str) -> list:
    """Find all .gguf files in the given directory (non-recursive)."""
    path = Path(directory)
    if not path.is_dir():
        return []
    out = []
    try:
        for f in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if f.is_file() and f.suffix.lower() == ".gguf":
                out.append(str(f))
    except (PermissionError, OSError):
        pass
    return out


def _windows_drives() -> list:
    """Return list of accessible drive roots on Windows (e.g. ['C:\\', 'D:\\'])."""
    if os.name != "nt":
        return ["/"]
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            drives.append(root)
    return drives


def browse_dir(directory: str) -> dict:
    """List immediate subdirectories + .gguf files of `directory`.

    Empty / "/" / "drives" → list of mounted drives (Windows) or "/" (POSIX).
    """
    if not directory or directory.lower() in ("drives", "drive", "root"):
        return {
            "path": "",
            "parent": None,
            "drives": _windows_drives(),
            "dirs": [],
            "files": [],
        }

    path = Path(directory)
    try:
        path = path.resolve()
    except (OSError, RuntimeError):
        pass

    if not path.exists() or not path.is_dir():
        return {"error": f"not a directory: {directory}"}

    dirs, files = [], []
    try:
        for entry in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            try:
                if entry.is_dir():
                    dirs.append(entry.name)
                elif entry.is_file() and entry.suffix.lower() == ".gguf":
                    files.append({"name": entry.name, "path": str(entry)})
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError) as e:
        return {"error": f"cannot read: {e}"}

    # parent — None at a drive root or filesystem root
    parent = str(path.parent) if path.parent != path else None

    return {
        "path": str(path),
        "parent": parent,
        "drives": _windows_drives(),
        "dirs": dirs,
        "files": files,
    }


# ── API handler ──────────────────────────────────────────────────────────────

class APIHandler(BaseHTTPRequestHandler):

    def _json(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    # ── GET routes ───────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._serve("index.html", "text/html; charset=utf-8")
        elif path == "/api/args":
            self._json(200, {"args": parse_args_file(ARGS_FILE)})
        elif path == "/api/profiles":
            self._json(200, {"profiles": load_profiles()})
        elif path.startswith("/api/profiles/"):
            # Accept both /api/profiles/<name> and /api/profiles/<name>/load —
            # loading a profile is a read, so GET should just work.
            rest = path.split("/api/profiles/", 1)[1]
            name = unquote(rest.replace("/load", "").rstrip("/").split("/")[0])
            profiles = load_profiles()
            if name in profiles:
                self._json(200, {"ok": True, "args": profiles[name], "profile": profiles[name]})
            else:
                self._json(404, {"error": "profile not found"})
        elif path == "/api/models":
            qs = self._query()
            directory = (qs.get("dir", [""])[0]
                         or self.headers.get("X-Model-Directory", "")
                         or str(BASE))
            self._json(200, {"dir": directory, "models": discover_models(directory)})
        elif path == "/api/browse":
            qs = self._query()
            directory = qs.get("dir", [""])[0]
            self._json(200, browse_dir(directory))
        elif path == "/api/status":
            pid = PID_FILE.read_text().strip() if PID_FILE.exists() else ""
            ready = bool(pid) and llama_server_ready()
            self._json(200, {
                "running": bool(pid),
                "ready": ready,
                "pid": pid,
                "port": _parse_port_from_args(),
            })
        elif path == "/api/current-dir":
            self._json(200, {"dir": str(BASE)})
        elif path == "/style.css":
            self._serve("style.css", "text/css")
        elif path == "/app.js":
            self._serve("app.js", "application/javascript")
        else:
            self._json(404, {"error": "not found"})

    # ── POST routes ──────────────────────────────────────────────────────

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._read_body()

        if path == "/api/save":
            data = json.loads(body) if body else {}
            line = build_args_line(data)
            ARGS_FILE.write_text(line + "\n", encoding="utf-8")
            self._json(200, {"ok": True, "line": line})

        elif path == "/api/start":
            try:
                pid = start_server()
                self._json(200, {"ok": True, "pid": pid})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/stop":
            ok = stop_server()
            self._json(200, {"ok": ok})

        elif path == "/api/opencode": # <-- Changed from /api/launch-opencode
            try:
                launch_opencode()
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/profiles":
            data = json.loads(body) if body else {}
            profiles = load_profiles()
            name = data.get("name", "Untitled")
            profiles[name] = data.get("args", {})
            save_profiles(profiles)
            self._json(200, {"ok": True, "profiles": profiles})

        elif path.startswith("/api/profiles/") and path.endswith("/load"):
            name = path.split("/api/profiles/", 1)[1].replace("/load", "").rstrip("/")
            name = unquote(name)
            profiles = load_profiles()
            if name in profiles:
                self._json(200, {"ok": True, "args": profiles[name]})
            else:
                self._json(404, {"error": "profile not found"})

        else:
            self._json(404, {"error": "not found"})

    # ── DELETE routes ────────────────────────────────────────────────────

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/profiles/"):
            name = path.split("/api/profiles/", 1)[1].split("/")[0]
            name = unquote(name)
            profiles = load_profiles()
            if name in profiles:
                del profiles[name]
                save_profiles(profiles)
                self._json(200, {"ok": True, "profiles": profiles})
            else:
                self._json(404, {"error": "profile not found"})
        else:
            self._json(404, {"error": "not found"})

    # ── static file serving ──────────────────────────────────────────────

    def _serve(self, filename, content_type):
        filepath = STATIC_BASE / filename
        if not filepath.exists():
            self._json(404, {"error": f"{filename} not found"})
            return
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # silent
        pass


# ── main ─────────────────────────────────────────────────────────────────────

def main(port=8082):
    server = HTTPServer(("127.0.0.1", port), APIHandler)
    print(f"Llama Config UI -> http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8082
    main(port)
