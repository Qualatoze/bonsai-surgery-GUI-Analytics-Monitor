# Bonsai GUI
Language: RU, EN, CN

https://i.imgur.com/dsdDaSw.png
https://i.imgur.com/SglGs3d.png
https://i.imgur.com/iQK6egp.png

## Install

```bash
mkdir bonsai
cd bonsai
git clone https://github.com/professorpalmer/bonsai-ada-surgery.git
git clone https://github.com/Qualatoze/bonsai-surgery-GUI-Analytics-Monitor
cd "bonsai-surgery-GUI-Analytics-Monitor"
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python main.py        # Windows
python3 main.py       # macOS / Linux
```

A PySide6 desktop control panel for [Bonsai 2 27B](https://github.com/professorpalmer/bonsai-ada-surgery).

Launch and stop the `llama-server.exe`, monitor CPU / RAM / VRAM in real time, inspect
usage statistics, and manage launch configuration — all from a native Qt window instead of
juggling PowerShell flags.

> **Tested on:** Windows 10.
> **macOS / Linux:** the code is portable but has not been verified yet — PRs welcome.

---

## Features

- **Launch tab** — pick a `.gguf` model, choose context length and KV cache type, toggle MTP
  speculative decoding, apply built-in presets (12 GB fast, 8 GB long-context, RTX 4070 SUPER,
  etc.), and start / stop `llama-server.exe` in one click. Advanced settings are inline in a
  scrollable two-column panel — no separate dialog needed. A **Recent** preset auto-saves the
  last launch config and re-applies it on next GUI start.
- **Monitor tab** — live KPI cards (PID, CPU %, RSS, pagefile, VRAM, system RAM), rolling
  resource chart, and a single stderr log viewer with cached `/health` readiness checks.
- **Analytics tab** — cache-aware token cost breakdown (Input / Output / Cached-input) in USD,
  stacked bar chart with drill-down, per-model deep-dive, hour-of-week heatmap, and a sortable
  data table. Auto-selects the currently running model on load. Reads from SQLite `agent_usage`
  table or a CSV at `data_path`.
- **Settings tab** — three-tier pricing (input / output / cached-input per 1M tokens, always USD),
  7 color schemes, path overrides, language (EN / RU / CN), refresh interval, retention
  policy for the SQLite stats store, and LAN network configuration.
- **Performance Mode** — hides the window to the system tray and clears all matplotlib
  figures so the LLM server gets maximum VRAM. Toggle via toolbar, tray menu, or
  `Ctrl+Shift+P`.
- **Robust subprocess handling** — PID file with `create_time` validation (survives PID
  reuse), cross-process lock file, stderr / stdout drain threads, graceful `taskkill /T`
  on Windows. NVML fallback for per-process VRAM when `nvidia-smi --query-compute-apps` is empty.

---

## Requirements

| Component | Version |
|---|---|
| Python | 3.10 or newer |
| OS | Windows 10 (tested); macOS 12+ / Linux (untested) |
| GPU | NVIDIA, with `nvidia-smi` on `PATH` (optional — the GUI degrades gracefully; NVML fallback via `pynvml`) |
| Disk | ~50 MB for the GUI + the Bonsai bundle (~6 GB of models) |

Python dependencies are listed in [`requirements.txt`](requirements.txt):

```
PySide6>=6.8.0
matplotlib>=3.8.0
numpy>=1.24.0
pandas>=2.2.0
psutil>=5.10.0
requests>=2.31.0
nvidia-ml-py  # optional — NVML fallback for per-process VRAM (GPU-only)
```

On first launch the app creates:

- `settings.json` — runtime configuration (safe to edit; validated on load).
- `artifacts/logs/gui.log` — application log (also written on uncaught exceptions).
- `artifacts/api_key.txt` — read-only; the GUI picks up the key the `.ps1` generated.
- `artifacts/stats.db` — SQLite store for resource samples.

The main window opens on the **Launch** tab. Pick a model, choose a preset, and click
**Start Server**.


## Configuration

`settings.json` lives next to `main.py` (or next to the `.exe`). The fields most likely
to need adjustment after you move the bundle:

| Field | Purpose |
|---|---|
| `models_dir` | Directory scanned for `.gguf` files (defaults to `../bonsai-ada-surgery/models`). |
| `llama_server_exe` | Full path to `llama-server.exe` (defaults to `../bonsai-ada-surgery/bin/llama-server.exe`). |
| `api_key_path` | Path to `artifacts/api_key.txt`. If the file is missing, the server runs without an API key. |
| `host` / `port` | Bind address for `llama-server` (default `0.0.0.0:8080`). |
| `data_path` | CSV the Analytics tab reads (optional — SQLite is primary). |
| `theme_name` | One of `dracula`, `solarized_dark`, `solarized_light`, `nord`, `monokai`, `one_dark`, `github_dark`, `tokyo_night`. |
| `language` | `en`, `ru`, or `cn`. |
| `last_launch` | Auto-saved last launch config (model + preset index). Applied as "Recent" preset on next start. |

The **Settings** tab can edit most of these at runtime and writes back atomically.

### Analytics data

The Analytics tab reads from the SQLite `agent_usage` table (primary source) or a CSV
at `data_path` with the columns:

```
timestamp, model_name, prompt_tokens, completion_tokens, cached_tokens, cost
```

`timestamp` accepts ISO 8601, or a Unix epoch in seconds / milliseconds / microseconds /
nanoseconds (auto-detected). `cached_tokens` may also be spelled
`prompt_cached_tokens` or `cache_hit_tokens`. `cost` is optional — if prices are set in
the Settings tab, cost is recomputed per the current rate card.

```markdown
# Bonsai 2 27B — Control Panel

A PySide6 desktop app to launch, monitor, and analyze a `llama-server` instance running Bonsai 2 27B GGUF models. Built for the patched `llama.cpp` from [professorpalmer/bonsai-ada-surgery](https://github.com/professorpalmer/bonsai-ada-surgery).

## Features
- Start/stop `llama-server` with selectable model, context size, and KV cache type.
- Advanced settings: MTP speculative decoding, KV VRAM cells, sampling, and more.
- Real‑time CPU/RAM/VRAM monitoring with live charts.
- Token usage analytics (prompt, completion, cached) and cost calculation.
- Preset configurations (e.g., for 8 GB / 12 GB GPUs).
- System tray "Performance Mode" — hides GUI, keeps server running.
- Multi‑language UI (EN/RU/CN), 8 color themes.

## Requirements
- Windows 10/11 (primary target; Linux/macOS need adaptation for GPU monitoring and process termination).
- Python 3.9+
- NVIDIA GPU with drivers (for `nvidia-smi`-based VRAM monitoring).
- `llama-server.exe` from the [PrismML fork](https://github.com/PrismML-Eng/llama.cpp) (or built from `bonsai-ada-surgery`).
- Bonsai 2 27B `.gguf` model file(s).

## Quick Start
1.
git clone https://github.com/your-username/bonsai-control-panel.git
download bonsai build here https://github.com/professorpalmer/bonsai-ada-surgery (https://github.com/professorpalmer/bonsai-ada-surgery/releases/download/bundle-20261020/bonsai-bundle-win-x64.zip)
cd bonsai-control-panel
python -m venv .venv
.venv\Scripts\activate
python main.py

   On first launch, `settings.json` and `artifacts/stats.db` are created automatically. Configure paths and token prices in the **Settings** tab.

## Configuration
All settings live in `settings.json` (auto‑created). Key fields:
- `llama_server_exe` – path to `llama-server.exe`
- `models_dir` – folder with `.gguf` models
- `host`, `port` – API server address
- `price_input_per_1m`, `price_output_per_1m`, `price_cached_input_per_1m` – token prices in USD
- `theme_name`, `language` – UI preferences

## Using with `bonsai-ada-surgery`
This panel expects the patched `llama-server` from the `bonsai-ada-surgery` project (or compatible forks) to enable MTP drafting and tiered KV cache. Make sure the binary is built with the required features.

## Credits

- **[professorpalmer/bonsai-ada-surgery](https://github.com/professorpalmer/bonsai-ada-surgery)** —
  the engine, patches, and recipe docs this GUI wraps. All performance numbers and
  defaults (context sizes, KV quantization, MTP tuning) come from that repository.
- **[PrismML-Eng/llama.cpp](https://github.com/PrismML-Eng/llama.cpp)** — the fork that
  serves Bonsai 2 27B.
- **Bonsai 2 27B** — model weights by PrismML.
