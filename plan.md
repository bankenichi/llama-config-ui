# plan.md

This file is a stub. The original scratch design notes have been superseded
by the actual implementation. For installation, layout, API reference, and
file structure see [README.md](./README.md).

## Code map (one-liners)

- `server.py` — Python stdlib HTTP server. Parses / writes `llama-args.txt`,
  serves the SPA, exposes the `/api/*` endpoints, runs the folder browser,
  starts and stops `run-llama.ps1`.
- `index.html` — single-page UI. Top section is **Common Settings**, the rest
  are tagged `.advanced-only` and revealed by a single toggle.
- `app.js` — client logic. The `idMap` translates canonical llama-server arg
  names to `f-*` form field IDs. `buildArgs()` emits only flags that differ
  from their HTML defaults, so saved files stay tidy.
- `style.css` — dark theme. Sections stack `.field-group` blocks; each block
  is a responsive grid of labels, separated by hairlines.
- `start.bat` — opens the browser and runs `server.py` on port 8082.

## Where things live

- `../llama-args.txt` — the file the UI reads on load and writes on save.
- `../run-llama.ps1` — what the **Start Server** button invokes.
- `./profiles.json` — created on first profile save.
- `../server.pid` — created while llama-server is running.

## Changelog

### 2026-05-25 — Muted hints on every flag

Added data-hint attributes to all 176 form fields in index.html, a .hint
CSS class in style.css, and DOM rendering logic in pp.js that inserts a
muted italic hint span below each label.

Hints were researched against the [llama.cpp source](https://github.com/ggml-org/llama.cpp)
to cover every flag including speculative-decoding, CPU, sampling, and special
settings.
