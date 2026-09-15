# Bob — local GPU speech-to-speech assistant

Desktop voice assistant: **wake word** or **global hotkey** starts listening, the same hotkey **toggles off** to send. Short pauses do not end the turn unless you enable **Auto-endpoint**.

Pipeline: streaming Faster-Whisper (CUDA) → Ollama → streaming Kokoro TTS (CPU). While Bob is speaking you can interrupt with the hotkey, or with your voice (**barge-in**, headphones assumed).

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

## Install as a Windows app

After setup, register Bob so it appears in the Start Menu, Apps list, and **Settings → Personalization → Taskbar → Other system tray icons** (like other tray apps):

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Or double-click `install.bat`. This creates a branded `Bob.exe`, a Start Menu shortcut, and an Apps & Features uninstall entry. Launch Bob once after installing so Windows adds it to the tray-icon list.

```powershell
.\uninstall.ps1
```

removes the Windows app registration. It does not delete this folder, `.venv`, or downloaded models.

To remove many broken or duplicate installs (especially when Apps & Features fails with `Config.Msi` / Error 5 on a non-C: drive):

```powershell
powershell -ExecutionPolicy Bypass -File .\cleanup-bob-installs.ps1 -Drive I: -Force
```

If BOB still appears in **Settings → Apps** after cleanup, the MSI entries are probably under **HKLM**. Run elevated:

```powershell
Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File .\cleanup-bob-installs.ps1 -RegistryOnly -Force'
```

Add `-WhatIf` to preview. Use `-ClearSetupCache` to also remove the embedded-installer extract cache.

## Turn-key installer (MSI / Burn)

Build a per-user installer folder under `installer\out\`. `BobSetup.exe` is a dark-themed setup UI that lets the user choose where Bob and all dependencies are installed, then runs Ollama (if needed), copies Bob files, downloads Python/PyPI packages, and launches the setup wizard. Large dependencies are downloaded on the target PC, keeping the MSI small (Bob source + scripts only).

Prerequisites on the build machine: [WiX Toolset 3.14+](https://wixtoolset.org/), Python 3.12 (project `.venv` from `setup.ps1`), and .NET Framework (`csc.exe`).

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\scripts\build.ps1
```

Run `installer\out\BobSetup.exe` on the target PC (no admin, internet required for first install). **Distribute `BobSetup.exe` alone** — it embeds `Bob.msi`, helper EXEs, `logo.png`, and `license.rtf`. On first run it extracts those files to `%LOCALAPPDATA%\BOB\setup\payload-cache\`. The setup UI asks for an install folder, shows download sizes/speed/ETA during dependency setup, then runs the model wizard. Existing Ollama and Python 3.12 installs are detected and skipped when possible. Ollama is left installed if the user later removes Bob from Apps & Features. NVIDIA GPU drivers are not bundled.

Silent install (uses the VRAM recommendation, default hotkey, and Start with Windows):

```powershell
.\installer\out\BobSetup.exe /quiet
```

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
| Auto-send after a pause | Off by default; enable **Auto-endpoint** in settings or the tray |
| Interrupt Bob | Hotkey, or speak over him when **Voice barge-in** is on (headphones) |
| Start listening | Wake word `hey_jarvis` |
| Overlay | Optional; **Show overlay** on the tray menu |
| Theme | Tray → Appearance (presets) or **Customize…** for colours and font |
| Memories | Tray → Memories… (edit / disable / delete / forget all) |
| Start with Windows | Tray → Startup |

All fields are also in **All settings…** and [`config.yaml`](config.yaml).

## Tools

Bob can call tools mid-turn: it runs them, then speaks the result. Tools run automatically with no confirmation, so the same hotkey that cancels a reply also cancels a tool. Each call is capped by `tool_timeout_sec`, and one turn may use up to `max_tool_rounds` rounds of tool calls before Bob has to answer in words.

Turns are orchestrated by a **LangGraph** state machine (retrieve → orchestrator → tools/memory/speaker → spoken-reply gate → optional validator). The same local Ollama model plays every specialist role. After speech, a background **prompt lab** scores replies, and can auto-apply a new `prompts/system.txt` when a shadow eval improves quality. Versions live in `prompts/versions/`; a live score drop rolls the prompt back and pins it for `prompt_cooldown_hours`.

Built in: `get_current_time`, `open_url`, `notes_read`, `notes_write` (`data\notes.md`), `memory_search`, `set_speech_mood`, `list_speech_moods`.

Speech moods change how Kokoro delivers the rest of the turn (rate, pitch, loudness, pauses) without swapping the selected voice. The model can call `set_speech_mood`, a tool can call `ctx.set_mood("excited")`, or a reply can start with `[mood:excited]`. Default mood is `tts_mood` in settings (also on the tray Voice menu). See [`sdk_examples/10_speech_mood.md`](sdk_examples/10_speech_mood.md).

The voice model has to support tool calling. The default `qwen2.5:latest` does; so do `qwen3`, `llama3.1`, and `mistral-nemo`. Turn tools off in settings if you switch to a model that does not.

### Writing a tool

Drop a Python file into `data\tools\` and restart Bob. Type hints and the docstring become the schema the model sees:

```python
from bob.tools import ToolContext, ToolError, tool

@tool
def roll_dice(sides: int = 6) -> str:
    """Roll a die and report the result.

    Args:
        sides: Number of sides on the die.
    """
    import random
    return f"Rolled a {random.randint(1, sides)}."
```

Add a `ctx: ToolContext` parameter (keyword-only, or last) to reach `ctx.settings`, `ctx.memory`, `ctx.data_dir`, `ctx.cancel`, `ctx.status(...)`, and `ctx.set_mood(...)`. It is injected by Bob and never shown to the model. Raise `ToolError` for bad input; return a short string, since whatever you return is read aloud. See [`data\tools\_example.py`](data/tools/_example.py) for a working template, and [`sdk_examples/`](sdk_examples/README.md) for commented walkthroughs of arguments, context, errors, HTTP, state, MCP, tests, and speech mood.

### MCP servers

List servers in [`config.yaml`](config.yaml). Both stdio (`command`) and Streamable HTTP (`url`) work, and their tools are exposed to the model as `serverid_toolname`:

```yaml
mcp_servers:
  - id: files
    enabled: true
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/me/notes"]
  - id: local
    enabled: true
    url: http://127.0.0.1:8000/mcp
```

A server that fails to start is skipped with a warning; Bob still runs. `.\run.ps1 --check` prints every tool Bob can see and any load errors.

## VRAM (10 GB)

Bob keeps Whisper and a 7B Ollama model resident, and leaves TTS / wake-word on CPU.

- Ollama `qwen2.5:latest`, `num_ctx=4096`, `keep_alive=-1`
- Whisper `large-v3-turbo` `int8_float16`
- `OLLAMA_GPU_OVERHEAD` reserved in `run.ps1` for a *new* Ollama process

Do not pick `gemma4` (~9.6 GB) as the voice model — there will be no room for Whisper. If CUDA runs out of memory, Whisper falls back to `distil-large-v3` then `medium` without unloading the LLM.

If Whisper OOMs against an already-running Ollama daemon, restart Ollama from a shell that has the env vars in `run.ps1`, then start Bob again.
