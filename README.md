# Llama Config UI

A local web UI for editing `llama-server` flags, saving named profiles, and starting / stopping the server — without ever editing `llama-args.txt` by hand or memorising the command line.

It runs entirely on `127.0.0.1`, talks to a small Python stdlib HTTP server, and stores everything in plain files next to the `llamacpp` binaries.

It won't create the file if its not already there. And it won't create the .ps1 either, as this was made for use with my **[Homelab Deployment](https://github.com/bankenichi/Homelab-Deployment)** stack. However you can easily create the an empty `llama-args.txt` file and after selecting your flags it should be able to save them. As for the run-llama.ps1 file...

Paste this into a file and save it as run-llama.ps1 copy-paste that file into your llamacpp folder (by default the scripts in this repo assume it to be in C:/Program Files/llamacpp, further modifications might be required if you install it elsewhere):

```
$exePath = "Path to your llama-server.exe"
$argsFile = "Path to your llama-args.txt"
if (!(Test-Path $argsFile)) { Write-Error "Config not found: $argsFile"; exit 1 }
$argsText = (Get-Content $argsFile -Raw).Trim()
$argsList = [regex]::Matches($argsText, '(?:"[^"]*"|[^\s]+)') | ForEach-Object { $_.Value }
Write-Host "Booting llama-server..." -ForegroundColor Cyan
& $exePath @argsList
```

## Quick start

```text
1.  Double-click  start.bat
2.  Browser opens at  http://127.0.0.1:8082
3.  Pick a model -> tweak flags -> Save to args.txt -> Start Server
```

The launcher does two things: opens the page in your default browser and runs `server.py` on port `8082`. Close the terminal window to shut everything down.

To run by hand:

```powershell
python server.py        # uses port 8082
python server.py 9000   # bind a different port
```

The server binds to loopback only.

## How it's laid out

The form is split into two zones:

- **Common Settings** — model path, mmproj path, context size, GPU layers, CPU MoE, keep tokens, parallel slots, port, threads, sampling basics (temp / top-p / min-p / top-k), spec-decoding tuning, cache type K/V, plus the four checkboxes most people change (`mlock`, `mmap`, `jinja`, `context-shift`). This covers everything in a typical `llama-args.txt`.
- **Show advanced settings** (single checkbox) — reveals every other flag the binary supports, grouped by topic: General, GPU, Memory, Context, Sampling, Server, Generation & Chat, Speculative draft, CPU, Special. Each section's fields are clustered by control type — text/number, then dropdowns, then checkboxes — separated by hairlines.

Your choice of advanced on / off is remembered in `localStorage`.

## How `llama-args.txt` round-trips

The server **parses** `llama-args.txt` on every load and normalises everything to canonical long-form flag names. Short aliases like `-m`, `-c`, `-np`, `-ngl`, `-ctk`, `-ctv`, `-fa` are translated to their long forms. Negation flags like `--no-mmap` are stored as `mmap: false` so the corresponding checkbox can be unchecked.

The server **writes** `llama-args.txt` based on what the form sends. Two rules keep the file tidy:

1. **A checkbox is only written when it differs from the HTML default.** If `--cont-batching` is default-on and you didn't touch it, it doesn't get emitted. If you explicitly turn off a default-on toggle, `--no-X` is written. If the original file contained `--no-X` for a default-off toggle, that negation is preserved.
2. **A dropdown is only written when its value differs from the default-selected option.** So `--flash-attn auto` (the default) is silently dropped.

Anything the server sees that doesn't map to a known UI field is preserved in memory and written back unchanged on save — so an obscure flag you set by hand won't get lost just because the UI doesn't know about it.

## Folder browser

The "🗂 Browse…" button opens a server-side folder picker. It lists subdirectories and `.gguf` files, supports navigation up the tree, and shows mounted drives on Windows. **Use this instead of the browser's native folder picker** for paths inside `C:\Program Files\` — Chrome and Edge block their built-in directory picker on system folders, but the server has no such restriction.

## Profiles

Profiles are named bundles of flags stored in `profiles.json`. Save the current form as a profile via the "💾 Save Profile" button; load one by picking it from the dropdown. Profiles only store flags that differ from defaults (same rule as the args file), so a profile JSON is short and easy to read.

```json
{
  "default": {
    "model": "C:\\Program Files\\llamacpp\\Qwen3...gguf",
    "ctx-size": "262144",
    "n-gpu-layers": "999",
    "mlock": true,
    "mmap": false,
    "jinja": true
  }
}
```

## Server control

- **▶ Start Server** runs `run-llama.ps1` in the `llamacpp` directory via PowerShell, records the PID in `server.pid`.
- **⏹ Stop Server** reads that PID and runs `taskkill /F /PID …`.
- The status pill polls `/api/status` every 10 s.
- **Launch Opencode** runs Opencode and launches it into a separate terminal.

This is intentionally minimal — it doesn't capture stdout or restart on crash. For long-running production setups you'd want something heavier.

## API

All endpoints return JSON. All paths are loopback only.

| Method   | Path                                  | Purpose                                                   |
|----------|---------------------------------------|-----------------------------------------------------------|
| GET      | `/api/args`                           | Parsed `llama-args.txt` as `{arg-name: value}`            |
| POST     | `/api/save`                           | Body = arg dict; writes `llama-args.txt`                  |
| GET      | `/api/status`                         | `{running, pid}`                                          |
| POST     | `/api/start`                          | Launches `run-llama.ps1`                                  |
| POST     | `/api/stop`                           | Kills the recorded PID                                    |
| GET      | `/api/profiles`                       | All profiles                                              |
| POST     | `/api/profiles`                       | `{name, args}` — save / overwrite profile                 |
| GET      | `/api/profiles/<name>`                | One profile (`{ok, args, profile}`)                       |
| GET/POST | `/api/profiles/<name>/load`           | Load a profile (`{ok, args}`)                             |
| DELETE   | `/api/profiles/<name>`                | Delete a profile                                          |
| GET      | `/api/models?dir=<path>`              | `.gguf` files in `<path>` (defaults to llamacpp dir)      |
| GET      | `/api/browse?dir=<path>`              | Subfolders + `.gguf` files; `dir=drives` lists Windows drives |
| GET      | `/api/current-dir`                    | The llamacpp install dir                                  |

## File layout

```
llamacpp/
├── llama-args.txt          ← the active config the UI reads / writes
├── run-llama.ps1           ← script the UI starts the server with
└── llama-config-ui/
    ├── server.py           ← Python stdlib HTTP server + REST API
    ├── index.html          ← single-page UI
    ├── app.js              ← client logic (vanilla ES6)
    ├── style.css           ← dark theme
    ├── start.bat           ← launcher (opens browser + runs server)
    ├── profiles.json       ← named profile bundles (created on first save)
    └── README.md
```

## Requirements

- Windows (PowerShell launcher + `taskkill` for stop).
- Python 3.10+ (uses the `:has()` CSS selector elsewhere — modern Chromium/Edge fine).
- `run-llama.ps1` in the parent `llamacpp/` folder (the UI calls it on Start).

Linux / macOS support would mostly mean swapping the `start_server` / `stop_server` helpers in `server.py` (PowerShell → `bash`; `taskkill` → `kill`). The rest of the codebase is platform-neutral.
