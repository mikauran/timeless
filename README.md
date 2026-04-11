# Timeless — Holographic Meeting Intelligence

> **v0.2** · AI-powered meeting system that turns spoken requirements into a running web application in real time.

Timeless listens to your team's conversation, extracts software requirements from speech, evaluates their completeness, and autonomously generates and deploys a working web application — all displayed on a futuristic holographic floating-panel interface.

---

## What It Does

1. **Listen** — A microphone captures the meeting. Faster-Whisper or OpenAI Whisper transcribes speech continuously.
2. **Understand** — An LLM analyses each transcription to extract requirements, update meeting notes, and detect when the discussion is complete.
3. **Evaluate** — The system reviews requirements for gaps and provides proactive advisor suggestions to the team.
4. **Generate** — When requirements are approved, the OpenCode agent writes, installs, and launches a full-stack web application.
5. **Display** — A Next.js holographic UI shows all panels (Requirements, Epics, Mind Map, Notes, Advisor, Output, Code) in an animated 3-D carousel.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Timeless UI  :3000                     │
│           Next.js 14 · Holographic carousel UI           │
│     SSE listener ──► projectDataProvider component       │
└────────────────────────┬─────────────────────────────────┘
                         │ SSE  /  REST
        ┌────────────────▼────────────────┐
        │    Manager Service  :8082        │
        │  FastAPI · single worker        │
        │  LLM orchestration · state mgmt │
        └──┬────────────┬────────────┬───┘
           │            │            │
  ┌────────▼───┐  ┌─────▼─────┐  ┌──▼──────────────────┐
  │Transcription│  │Requirements│  │  OpenCode Service   │
  │Service :8080│  │Service :8081│  │  (web codegen):8084 │
  │Whisper STT  │  │FastAPI      │  │  Writes & runs app  │
  └────────────┘  └────────────┘  └─────────────────────┘
```

All backend services are Python/FastAPI. Communication is via REST and Server-Sent Events (SSE).

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10 + | 3.11 recommended |
| Node.js | 18 + | For the Next.js frontend |
| npm | 9 + | Installed with Node.js |
| Microphone | — | Required for speech input |
| Speakers / headphones | — | Required for TTS welcome message |
| OpenAI API key | — | Or OpenRouter / local Ollama |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/GPT-Laboratory/timeless-architecture-base.git
cd timeless-architecture-base
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your values. Minimum required:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_GENERAL_MODEL=gpt-4o-mini
TRANSCRIPTION_METHOD=rest
OPENCODE_MODEL=openai/gpt-4o
```

See `.env.example` for all options including OpenRouter and Ollama.

### 3. Run the installer / launcher

```bash
# Standard setup — OpenAI Whisper API for transcription (recommended)
python bootstrap.py --web --opencode

# CPU transcription (local faster-whisper, no API cost)
python bootstrap.py --web --opencode --cpu

# GPU transcription (CUDA)
python bootstrap.py --web --opencode --gpu
```

`bootstrap.py` will:
- Create a Python virtual environment (`venv/`)
- Install all Python dependencies from `requirements.txt`
- Run `npm install` in `timeless_ui/` (first run only)
- Start all backend services
- Start the Next.js dev server
- Open your browser at `http://localhost:3000`

---

## Usage

1. Open `http://localhost:3000` in your browser.
2. Click the **Initialise** button — Timeless greets you and activates the microphone.
3. Start your meeting. Speak naturally about the software you want to build.
4. Watch the panels update in real time:
   - **Requirements** — extracted feature list
   - **Epics** — grouped feature epics
   - **Mind Map** — visual tree of the product
   - **Notes** — auto-generated meeting minutes
   - **Advisor** — gap analysis and suggestions
   - **Output** — live preview of the generated app
   - **Code** — browse the generated source files
5. When the LLM decides requirements are complete, code generation starts automatically — a progress overlay appears on the active panel.
6. The generated app opens in the **Output** panel once running.

### Panel Navigation

- Click any side-panel in the carousel to bring it to focus (animated slide).
- Use the **icon sidebar** on the left to jump directly to any panel.
- Click **Retry** on the error screen if the manager service isn't running.

---

## Service Ports

| Service | Port | Description |
|---|---|---|
| Next.js UI | 3000 | Holographic frontend |
| Transcription Service | 8080 | Whisper STT + TTS + mic control |
| Requirements Service | 8081 | Requirement extraction & storage |
| Manager Service | 8082 | LLM orchestration, SSE, state |
| OpenCode Service | 8084 | Web app code generation & runner |

---

## LLM Provider Options

### OpenAI (default)
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_GENERAL_MODEL=gpt-4o-mini
OPENCODE_MODEL=openai/gpt-4o
```

### OpenRouter
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o
OPENCODE_MODEL=openai/gpt-4o
```

### Ollama (fully local)
```env
LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
```
> Note: code generation quality depends heavily on model capability. GPT-4o or equivalent recommended.

---

## Transcription Options

| Mode | Flag | Requirement |
|---|---|---|
| OpenAI Whisper API | *(default)* | `OPENAI_API_KEY` in `.env` |
| Local CPU | `--cpu` | Downloads faster-whisper model on first run |
| Local GPU (CUDA) | `--gpu` | CUDA-enabled PyTorch |

Set `TRANSCRIPTION_METHOD=rest` for API or `local` for on-device.

---

## Project Structure

```
timeless-architecture-base/
├── bootstrap.py                  # One-command installer & launcher
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
│
├── manager_service/
│   └── manager_service.py        # Core orchestration (FastAPI)
│
├── transcription_service/
│   └── transcribe_service.py     # Whisper STT + TTS + mic (FastAPI)
│
├── requirements_service/
│   └── requirements_manager.py   # Requirement storage (FastAPI)
│
├── opencode/
│   └── web_code_generation_service.py  # OpenCode agent (FastAPI)
│
└── timeless_ui/                  # Next.js 14 holographic frontend
    └── src/app/
        ├── components/           # React components
        └── styles/               # CSS modules
```

---

## Troubleshooting

**"Cannot reach Timeless services" on UI**
The manager service (port 8082) is not running. Start it:
```bash
python bootstrap.py --web --opencode
```

**Microphone not detected**
Check your system audio input permissions and ensure a microphone is selected as the default input device.

**Code generation overlay not appearing**
Ensure only one instance of the manager service is running (the service must use a single worker). If you started it manually with `workers > 1`, restart with `python manager_service/manager_service.py`.

**`ModuleNotFoundError` on startup**
Run from inside the activated virtual environment or use `python bootstrap.py` which activates the venv automatically.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React 18, TypeScript, CSS Modules |
| UI Fonts | Space Grotesk, JetBrains Mono |
| Backend | Python 3.11, FastAPI, Uvicorn |
| LLM | OpenAI GPT-4o / OpenRouter / Ollama |
| Speech-to-Text | OpenAI Whisper API / faster-whisper |
| Text-to-Speech | OpenAI TTS |
| Code Generation | OpenCode agent |
| Realtime comms | Server-Sent Events (SSE) |

---

## Roadmap

- [ ] Multi-language meeting support
- [ ] Session export (PDF requirements doc, code zip)
- [ ] Persistent project history across sessions
- [ ] Voice commands for panel navigation
- [ ] Avatar hologram integration (SadTalker)
- [ ] Multi-user / remote meeting support

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Authors

| Name | Role |
|---|---|
| **Shahbaz Siddeeq** | PhD Researcher · Tampere University |
| **Jussi Rasku** | Tampere University |
| **Juha Ala-Rantala** | Tampere University |

---

## Citation

If you use Timeless in your research, please cite:

```
@software{timeless2026,
  author = {Siddeeq, Shahbaz and Rasku, Jussi and Ala-Rantala, Juha},
  title  = {Timeless: Holographic Meeting Intelligence for End-to-End Software Development},
  year   = {2026},
  url    = {https://github.com/shahbazsiddeeq/timeless-end-to-end-software-development}
}
```
