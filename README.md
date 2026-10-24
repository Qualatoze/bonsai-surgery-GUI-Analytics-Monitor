UI language: **RU · EN · CN**
## 📸 Screenshots

| Launch | Monitor |
| :---: | :---: |
| <img src="https://i.imgur.com/fWX2BCf.png" width="400" alt="Launch Tab"> | <img src="https://i.imgur.com/ECtvP2U.png" width="400" alt="Monitor Tab"> |

| Analytics | Settings |
| :---: | :---: |
| <img src="https://i.imgur.com/2JaG24Y.png" width="400" alt="Analytics Tab"> | <img src="https://i.imgur.com/tD3IEFk.png" width="400" alt="Settings Tab"> |

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
