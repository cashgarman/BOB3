# Bob — local GPU speech-to-speech assistant

Desktop voice assistant: **wake word** or **global hotkey** starts listening, the same hotkey **toggles off** to send. Short pauses in your speech do not end the turn.

Pipeline: Faster-Whisper (CUDA) → Ollama → Kokoro TTS (CPU).

## Requirements

- Windows, NVIDIA GPU with ~10 GB VRAM
- [Ollama](https://ollama.com) running (`qwen2.5:latest` is the default)
- Python **3.12** (`py -3.12`). System 3.14 cannot install CUDA Whisper wheels.
- CUDA 12 libraries are installed into `.venv` (no system CUDA toolkit required).

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

This creates a project-local `.venv` and installs dependencies.

## Run

```powershell
.\run.ps1
```

First launch downloads Whisper, Kokoro, and the wake-word model into `models\`.

Health check (no UI):

```powershell
.\run.ps1 --check
```

## Controls

Bob lives in the **system tray**. Right-click the icon for every setting. Left-click or double-click opens the main window.

| Action | Default |
|---|---|
| Open main window | Left-click or double-click the tray icon |
| Start / stop listening | `Ctrl+Shift+Space` or **Toggle listen** on the tray menu |
| Start listening | Wake word `hey_jarvis` |
| Overlay | Optional; **Show overlay** on the tray menu |
| Memories | Tray → Memories… (edit / disable / delete / forget all) |
| Start with Windows | Tray → Startup |

All fields are also in **All settings…** and [`config.yaml`](config.yaml).

## VRAM (10 GB)

Bob keeps Whisper and a 7B Ollama model resident, and leaves TTS / wake-word on CPU.

- Ollama `qwen2.5:latest`, `num_ctx=4096`, `keep_alive=-1`
- Whisper `large-v3-turbo` `int8_float16`
- `OLLAMA_GPU_OVERHEAD` reserved in `run.ps1` for a *new* Ollama process

Do not pick `gemma4` (~9.6 GB) as the voice model — there will be no room for Whisper. If CUDA runs out of memory, Whisper falls back to `distil-large-v3` then `medium` without unloading the LLM.

If Whisper OOMs against an already-running Ollama daemon, restart Ollama from a shell that has the env vars in `run.ps1`, then start Bob again.
