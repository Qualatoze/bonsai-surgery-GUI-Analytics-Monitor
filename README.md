# Bonsai GUI

A PySide6 desktop control panel for [Bonsai 2 27B](https://github.com/professorpalmer/bonsai-ada-surgery) — launch, monitor, and analyze a patched `llama-server` from a native Qt window instead of juggling PowerShell flags.

UI language: **RU · EN · CN**

![Launch tab](https://i.imgur.com/dsdDaSw.png)
![Monitor tab](https://i.imgur.com/SglGs3d.png)
![Analytics tab](https://i.imgur.com/iQK6egp.png)

## Install

```bash
mkdir bonsai && cd bonsai

Download bonsai build here https://github.com/professorpalmer/bonsai-ada-surgery (https://github.com/professorpalmer/bonsai-ada-surgery/releases/download/bundle-20261020/bonsai-bundle-win-x64.zip)
git clone https://github.com/Qualatoze/bonsai-surgery-GUI-Analytics-Monitor
cd bonsai-surgery-GUI-Analytics-Monitor

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python main.py

## Credits

- **[professorpalmer/bonsai-ada-surgery](https://github.com/professorpalmer/bonsai-ada-surgery)** —
  the engine, patches, and recipe docs this GUI wraps. All performance numbers and
  defaults (context sizes, KV quantization, MTP tuning) come from that repository.
- **[PrismML-Eng/llama.cpp](https://github.com/PrismML-Eng/llama.cpp)** — the fork that
  serves Bonsai 2 27B.
- **Bonsai 2 27B** — model weights by PrismML.
