# Sample tools that demonstrate speech mood

These are ordinary Bob SDK plugins: decorate a function with `@tool`, do some work, then call `ctx.set_mood(...)` **before** returning so the spoken paraphrase of the result uses that delivery.

They live here for documentation and in [`data/tools/`](../../data/tools/) so Bob loads them at boot (restart Bob, or toggle **Tools enabled**). Delete or rename a file with a leading `_` if you do not want it offered.

| File | Tools | Mood |
|---|---|---|
| [`sample_playful.py`](sample_playful.py) | `tell_joke`, `flip_luck`, `pep_talk` | upbeat / excited or sorry / warm |
| [`sample_quiet.py`](sample_quiet.py) | `guided_breath`, `whisper_reminder`, `comfort`, `sit_with_sadness` | calm / whisper / sorry / sad |
| [`sample_brisk.py`](sample_brisk.py) | `running_late`, `status_brief`, `celebrate` | hurried / serious / excited |

`flip_luck` is the important pattern: **the result picks the mood**, not a hardcoded tone.

## Try without the voice loop

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py sample_tools/sample_playful.py --call tell_joke
.venv\Scripts\python.exe sdk_examples\run_example.py sample_tools/sample_playful.py --call flip_luck
.venv\Scripts\python.exe sdk_examples\run_example.py sample_tools/sample_quiet.py --call guided_breath rounds=2
.venv\Scripts\python.exe sdk_examples\run_example.py sample_tools/sample_quiet.py --call whisper_reminder text="lock the back door"
.venv\Scripts\python.exe sdk_examples\run_example.py sample_tools/sample_brisk.py --call running_late
.venv\Scripts\python.exe sdk_examples\run_example.py sample_tools/sample_brisk.py --chat
```

The harness prints `[mood] …` when `set_mood` fires. In Bob, say the phrases in the file headers and listen for rate/pitch/loudness to change. Overlay detail shows `mood: excited` (and so on) while he is thinking or speaking.

## How a tool should do this

```python
from bob.tools import ToolContext, tool

@tool
def tell_joke(*, ctx: ToolContext) -> str:
    """Tell a short, clean joke."""
    ctx.set_mood("upbeat")
    return "Why did the scarecrow get promoted? He was outstanding in his field."
```

Set the mood first, return a short spoken string, do not mention the mood name. Unknown names raise `ToolError`. Canonical list: `neutral`, `calm`, `warm`, `upbeat`, `excited`, `serious`, `sad`, `sorry`, `whisper`, `hurried`.

The tutorial that only teaches the API (without these scenarios) is still [`10_speech_mood.md`](../10_speech_mood.md).
