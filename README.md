# Llama Config UI

Llama Config UI is a loopback-only web interface for configuring and controlling
`llama-server`. It began as a lightweight editor for `llama-args.txt` used by the
author's [Homelab Deployment](https://github.com/bankenichi/Homelab-Deployment)
stack. This repository now also contains a first-class control plane for the
personal
[`atomic-llama-cpp-turboquant`](https://github.com/bankenichi/atomic-llama-cpp-turboquant)
fork.

The two modes coexist:

- **Atomic mode** is the primary interface when this repository is checked out as
  `tools/llama-config-ui` in the Atomic worktree. It resolves typed model-stack
  settings through Atomic's canonical launcher, validates the selected binary and
  files, and manages a captured server process with readiness, logs, metrics, and
  diagnostics.
- **Generic mode** preserves the original `llama-args.txt` editor and detached
  `run-llama.ps1` workflow for other llama.cpp installations. It is available under
  “Generic llama.cpp argument editor (legacy compatibility).”

Everything binds to `127.0.0.1`. The backend uses only the Python standard library;
the frontend is plain HTML, CSS, and JavaScript.

## Atomic mode at a glance

Atomic mode supports the actual execution paths of the converged fork, rather than
only displaying a larger list of flags:

| Stack | Draft topology | Normal target KV | Vision |
|---|---|---|---|
| Ternary Bonsai 27B | Prism DSpark sidecar, `draft-dspark`, q8_0 K/V | turbo4 K / turbo3 V | Matching Bonsai mmproj |
| Qwen 3.6 35B-A3B | Embedded synchronous NextN, `draft-mtp` | turbo4 K / turbo3 V | Matching Qwen mmproj |
| Gemma 4 26B-A4B | Optional external assistant, `draft-mtp` | turbo4 K / turbo2 V | Matching Gemma mmproj |
| Gemma 4 12B dense | Target-only | q8_0 K / q8_0 V | Encoder-free Gemma projector |

For each stack the UI handles:

- target, draft/assistant, and mmproj topology;
- target and draft GPU layers and KV cache types, including TurboQuant;
- DSpark's current type, draft-slot limit, matching sidecar requirement, and the
  runtime-enforced 4096 positions per parallel slot;
- Qwen embedded NextN without an erroneous second draft-model path;
- Gemma assistant selection without conflating it with Qwen NextN;
- vision alongside text speculation—the UI never disables speculation merely
  because an mmproj is configured;
- context shifting, including warnings when TurboQuant K requires Atomic's
  transactional reprefill path;
- CPU MoE placement for applicable models;
- `GGML_SCHED_PREFETCH_EXPERTS`, `GGML_CUDA_REGISTER_HOST`, and
  `TURBO_LAYER_ADAPTIVE` as structured environment settings;
- reasoning, batching, host/port, metrics, and a conflict-checked additional-argv
  escape hatch;
- exact argv/environment preview, preflight errors, performance/correctness
  warnings, managed start/stop, readiness, logs, metrics, and a redacted diagnostic
  bundle.

The C++ server remains authoritative for GGUF parsing, ternary kernels, DSpark
graphs, image embedding, media-aware speculative fallback, prompt-cache coherence,
and context-shift transactions. The UI configures and observes these paths; it does
not reimplement inference behavior.

## Atomic architecture

```text
browser form
    |
    | typed JSON configuration
    v
server.py + atomic_runtime.py
    |
    | literal subprocess argv (no shell interpolation)
    v
atomic worktree/scripts/atomic-launcher.ps1
    |
    +-- profile resolution and validation
    +-- llama-server --help capability probe
    +-- exact argv and environment construction
    v
Atomic llama-server child
    +-- /health
    +-- /metrics (when enabled)
    +-- captured stdout/stderr
```

The PowerShell launcher is the shared contract used by the owner's local wrapper and
this UI. This prevents the UI from drifting to obsolete flags such as
`--spec-type mtp`, `--spec-type nextn`, or `--draft-max`.

## Quick start in the Atomic worktree

Clone the parent repository with submodules, or initialize the UI after cloning:

```powershell
git clone --recurse-submodules https://github.com/bankenichi/atomic-llama-cpp-turboquant
cd atomic-llama-cpp-turboquant

# Existing checkout:
git submodule update --init --recursive
```

Start the UI from the submodule:

```powershell
cd tools\llama-config-ui
python server.py          # http://127.0.0.1:8082
python server.py 9000     # choose a different UI port
```

The default location is inferred from the submodule layout:

- Atomic source root: two directories above this UI (`tools/..`);
- Atomic launcher: `scripts/atomic-launcher.ps1`;
- installed models: the launcher's normal `C:\Program Files\llamacpp` root;
- preferred binary: the first available Atomic convergence/build executable.

Override source discovery with `ATOMIC_LLAMA_ROOT`. Override PowerShell with
`ATOMIC_POWERSHELL` when `pwsh` or `powershell` is not discoverable on `PATH`.

## Recommended Atomic workflow

1. Select a starter profile or model stack.
2. Confirm target, draft/assistant, and mmproj paths.
3. Adjust context, KV, offload, and performance controls.
4. Click **Validate & preview**. Review both warnings and the exact redacted argv.
5. Click **Start Atomic server** only after preflight passes.
6. Wait for the status badge to report readiness before connecting a client.
7. Use the captured log and metrics panes for diagnosis.
8. Stop the exact managed PID from the UI when finished.

Starter profiles are immutable examples. Saved user profiles are stored separately
in ignored `atomic-profiles.json`, so local model paths and tuning do not enter Git.

### Ternary profiles

- **Ternary DSpark + Vision** is the normal integrated path.
- **Ternary Target + Vision** isolates target/mmproj behavior without DSpark.
- **Ternary DSpark Text** isolates speculative text generation without loading the
  projector.
- **Ternary Target Full-f16 Diagnostic** raises only target KV to f16 for controlled
  comparisons; the lossless DSpark cache remains q8_0/q8_0.

The UI rejects more than 16 DSpark draft tokens and a missing sidecar before
launch. The server enforces the draft model's 4096 positions per parallel slot. On
real media requests the server uses its safe target path and invalidates draft state;
later text speculation resumes only after the paired rebuild.

### Qwen profiles

**Qwen NextN Daily** uses target `turbo4`/`turbo3`, draft `f16`/`f16`, 28 CPU MoE
layers, and two synchronous draft tokens. The embedded NextN graph reopens the same
target GGUF internally, so the draft path is disabled. All-f16 target KV is a
diagnostic override, not the standard configuration.

### Gemma profiles

**Gemma 4 Daily** is the tuned target-only path. **Gemma 4 MTP** adds the historical
or modern assistant GGUF with draft `turbo3`/`turbo3`. The 12B profile is dense and
target-only. Vision is retained for all matching profiles.

## Capabilities and validation

Atomic mode runs the selected `llama-server --help` and combines the advertised
flags/speculative types with the fork's launcher schema. Required missing features
are preflight failures instead of silently omitted arguments. Changing the
executable and refreshing capabilities makes the UI evaluate the new binary.

Validation errors name the rejected setting and constraint. Warnings describe valid
but important behavior, including:

- media-turn target fallback and draft rebuild;
- TurboQuant K context shifts using reprefill;
- full-f16 KV memory cost;
- combining mmap host registration with expert prefetch despite its measured
  performance trade-off.

Additional argv is tokenized locally into a literal argument vector. It is not
passed through a shell. Raw values that try to override structured model, cache,
speculative, port, context, or offload fields are rejected so the displayed
configuration cannot disagree with the executed one.

## Managed process behavior

Atomic start performs a fresh preview/preflight before creating a child. The child:

- runs from the Atomic worktree;
- receives stdout and stderr redirected to `atomic-server.log`;
- records its exact PID and OS process-creation marker in `atomic-server.pid`, so a
  reused PID cannot be mistaken for the managed child after a UI restart;
- records its active overrides and redacted preview for restart-safe status and
  diagnostics.

Stop first sends a graceful process-group signal to the child. If it does not exit
within the configured timeout, the manager terminates that recorded process tree.
It never searches by executable name or kills unrelated llama-server instances.

Readiness probes `/health`. Metrics are fetched only when `--metrics` is enabled and
the endpoint exists. Missing metrics are reported as unavailable rather than shown
as fabricated zeros.

## Profiles and legacy migration

Atomic starter profiles live in `atomic-profiles.defaults.json`. Mutable profiles
live in ignored `atomic-profiles.json` with schema version 1.

**Import Program Files profiles** reads the older
`C:\Program Files\llamacpp\llama-config-ui\profiles.json` without modifying it. The
migration:

- infers Gemma, Qwen, or Ternary from unambiguous model/draft information;
- maps historical `mtp`, `nextn`, or `dspark` values to current speculative types;
- maps recognized flag names to typed Atomic settings;
- preserves unknown fields in `legacy_unknown` for manual review;
- backs up an existing destination user-profile file before merging imported data.

The source file is never rewritten, moved, or deleted.

## Generic llama.cpp mode

Generic mode retains the original installation behavior. It resolves the llama.cpp
runtime directory in this order:

1. `LLAMACPP_ROOT`;
2. legacy `LLAMACPP_DIR`;
3. `C:\Program Files\llamacpp`.

It reads and writes `llama-args.txt`, launches `run-llama.ps1`, and stores its
original named flag bundles in `profiles.json`. Use `llama-ui.bat` for the original
double-click workflow, or run `python server.py` directly.

The argument parser normalizes short aliases to current long names, preserves
negative numeric values, and represents `--no-X` as `X: false`. Unknown arguments
round-trip instead of being discarded. The advanced form remains an escape hatch
for general upstream options; Atomic mode should be preferred for this fork because
it understands cross-field invariants and environment features.

If a standalone deployment needs `run-llama.ps1`, this minimal form reads the saved
argument file as an array and invokes the binary:

```powershell
$root = $env:LLAMACPP_ROOT
if ([string]::IsNullOrWhiteSpace($root)) { $root = 'C:\Program Files\llamacpp' }
$exePath = Join-Path $root 'llama-server.exe'
$argsFile = Join-Path $root 'llama-args.txt'
if (!(Test-Path -LiteralPath $argsFile)) {
    Write-Error "Config not found: $argsFile"
    exit 1
}
$argsText = (Get-Content -LiteralPath $argsFile -Raw).Trim()
$argsList = [regex]::Matches($argsText, '(?:"[^"]*"|[^\s]+)') | ForEach-Object { $_.Value.Trim('"') }
& $exePath @argsList
```

## HTTP API

All endpoints return JSON and are available only through the loopback server.

### Atomic endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/atomic/describe` | Launcher schema, live binary capabilities, profiles, paths |
| POST | `/api/atomic/preview` | Resolve and validate `{stack, preset, overrides}` |
| POST | `/api/atomic/start` | Revalidate and start one managed child |
| POST | `/api/atomic/stop` | Gracefully stop, then force only the recorded child if needed |
| GET | `/api/atomic/status` | Process, readiness, health, and effective preview |
| GET | `/api/atomic/logs?lines=N` | Tail captured stdout/stderr |
| GET | `/api/atomic/metrics` | Current Prometheus text or an unavailable reason |
| GET | `/api/atomic/diagnostics` | Redacted preview, status, and log bundle |
| GET/POST | `/api/atomic/profiles` | Read or save versioned user profiles |
| DELETE | `/api/atomic/profiles/<name>` | Delete a mutable profile |
| POST | `/api/atomic/import-legacy` | Non-destructively import the old profile schema |

### Generic endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/args` | Parse `llama-args.txt` |
| POST | `/api/save` | Write the generic argument dictionary |
| GET/POST/DELETE | `/api/profiles...` | Original generic profile operations |
| GET | `/api/models?dir=<path>` | List `.gguf` files |
| GET | `/api/browse?dir=<path>` | Browse server-side directories and Windows drives |
| GET | `/api/status` | Original detached-server status |
| POST | `/api/start`, `/api/stop` | Original `run-llama.ps1` lifecycle |
| POST | `/api/opencode` | Launch the optional `opencode` CLI |

## File layout

```text
llama-config-ui/
├── atomic_runtime.py              Atomic launcher/profile/process adapter
├── atomic-profiles.defaults.json  immutable starter profiles
├── atomic.js                      Atomic browser behavior
├── atomic.css                     Atomic control-plane styles
├── server.py                      loopback HTTP server and both APIs
├── index.html                     combined Atomic and generic interface
├── app.js                         original generic editor behavior
├── style.css                      original UI theme
├── profiles.json                  original generic profiles
├── llama-ui.bat                   Windows convenience launcher
├── tests/test_atomic_runtime.py   stdlib unit tests
├── NOTICE.md                      source lineage and attribution
└── README.md
```

Ignored local state includes `atomic-profiles.json`, active configuration, PID, log,
and diagnostics files.

## Testing

Run backend tests and syntax checks from this directory:

```powershell
python -m unittest discover -s tests -v
python -m py_compile server.py atomic_runtime.py
node --check app.js
node --check atomic.js
```

For an integration check, start `server.py`, open `/api/atomic/describe`, preview
each stack, and verify the rendered form changes topology and cache defaults. Real
model launches should run as managed children with captured output and finite
external timeouts; backend faults must not take down the controlling terminal.

## Security and scope

- The HTTP server binds only to `127.0.0.1`; do not expose it through an untrusted
  proxy without adding authentication and request protections.
- Configuration may contain local paths. Diagnostics redact known secret argument
  values, but review exported bundles before sharing them.
- The UI manages only the process it created or recovered from its own PID record;
  recovery requires both the PID and OS creation marker to match.
- Concurrent ComfyUI, ACE-Step, Kobold, or secondary llama orchestration is outside
  this project. The current goal is correct primary-model operation.

## Provenance

The original UI, generic flag editor, Homelab integration, and repository history
are by `bankenichi`. Atomic launcher integration is a local adaptation for
`bankenichi/atomic-llama-cpp-turboquant` and calls that repository's own launcher;
it does not copy llama.cpp inference code into this project. Current option names
and behavior derive from the selected `ggml-org/llama.cpp` descendant binary.

See [`NOTICE.md`](NOTICE.md) for source URLs, preservation expectations, and the
relationship between the original UI and the Atomic adaptation.
