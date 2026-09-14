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
| Memories | Tray → Memories… (edit / disable / delete / forget all) |
| Start with Windows | Tray → Startup |

All fields are also in **All settings…** and [`config.yaml`](config.yaml).

## Tools

Bob can call tools mid-turn: it runs them, then speaks the result. Tools run automatically with no confirmation, so the same hotkey that cancels a reply also cancels a tool. Each call is capped by `tool_timeout_sec`, and one turn may use up to `max_tool_rounds` rounds of tool calls before Bob has to answer in words.

Built in: `get_current_time`, `open_url`, `notes_read`, `notes_write` (`data\notes.md`), `memory_search`.

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

Add a `ctx: ToolContext` parameter (keyword-only, or last) to reach `ctx.settings`, `ctx.memory`, `ctx.data_dir`, `ctx.cancel`, and `ctx.status(...)`. It is injected by Bob and never shown to the model. Raise `ToolError` for bad input; return a short string, since whatever you return is read aloud. See [`data\tools\_example.py`](data/tools/_example.py) for a working template.

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
