# Example 10 — Speech mood

**File:** [`10_speech_mood.py`](10_speech_mood.py)

How a tool (or the model) changes the *sound* of Bob's reply without swapping the selected Kokoro voice.

## What you learn

Kokoro has no emotion channel. Bob maps a short list of mood names onto:

| Knob | Where it is applied |
|---|---|
| Speaking rate | Kokoro `speed` × the user's `tts_speed` |
| Pitch | Semitone shift of the waveform (also slightly shortens or lengthens it) |
| Loudness | Gain in dB, then peak-limited |
| Pauses | Kokoro `sentence_pause` / `clause_pause` |

Canonical moods: `neutral`, `calm`, `warm`, `upbeat`, `excited`, `serious`, `sad`, `sorry`, `whisper`, `hurried`. Aliases such as `happy` → `upbeat` and `quiet` → `whisper` are accepted.

## Three equivalent entry points

```python
ctx.set_mood("excited")          # any SDK tool, including this example
```

```text
the model calls set_speech_mood  # built-in, offered every turn
```

```text
[mood:excited] That's great news.  # stripped before TTS and before memory
```

The mood lasts until the turn ends, then Bob returns to `tts_mood` from settings.

## The tools in this file

| Name | Mood it sets |
|---|---|
| `celebrate_win` | `excited` |
| `break_bad_news` | `sorry` |
| `hush` | `whisper` |
| `pick_mood` | whatever you pass; unknown names become `ToolError` |

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 10_speech_mood.py --schema

.venv\Scripts\python.exe sdk_examples\run_example.py 10_speech_mood.py --call celebrate_win

.venv\Scripts\python.exe sdk_examples\run_example.py 10_speech_mood.py --call pick_mood mood=grumpy

.venv\Scripts\python.exe sdk_examples\run_example.py 10_speech_mood.py --chat
```

`--call celebrate_win` should print `[mood] excited` from the harness, then a short instruction for the model. In `--chat`, try "I just got the job" and watch for a `set_speech_mood` or `celebrate_win` call before the spoken sentence.

To hear it in Bob, the scenario plugins in [`sample_tools/`](sample_tools/README.md) are already copied to `data/tools/` (joke, luck, breath, whisper notes, hurry). Restart Bob and ask for a joke.

## Next

[SDK_REFERENCE.md](SDK_REFERENCE.md#speech-moods) for the full mood table and `ToolContext` fields.
