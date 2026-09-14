# Built-in tools

Bob registers these tools automatically when `tools_enabled` is true in `config.yaml`. They are implemented under `bob/tools/builtin/` and exposed to the LLM through Ollama's tool-calling API.

User plugins in `data/tools/*.py` and MCP servers can add more tools alongside these.

## get_current_time

Returns the current local date and time in a spoken-friendly format.

| | |
|---|---|
| **Module** | `bob/tools/builtin/clock.py` |
| **Arguments** | none |
| **Use when** | The user asks what time or date it is, or you need the real clock instead of guessing. |

**Example result:** `Monday, September 14, 2026 at 3:45 PM PDT`

---

## conversation_log

Lists recent messages in the active chat session with timestamps.

| | |
|---|---|
| **Module** | `bob/tools/builtin/conversation.py` |
| **Arguments** | `limit` (optional, default 20, max 100) — how many recent messages to return, newest last |
| **Use when** | The user asks when they said something, how many prompts they sent, or what they asked earlier in this conversation. |

Requires an active chat session (`ToolContext.chat` and `session_id`). Returns one line per message: `timestamp Role: text`.

---

## notes_read

Reads the user's notes file.

| | |
|---|---|
| **Module** | `bob/tools/builtin/notes.py` |
| **Arguments** | none |
| **Storage** | `data/notes.md` |
| **Use when** | The user refers to saved notes or asks what is written down. |

Returns the file contents, or a message that the notes file is empty.

---

## notes_write

Saves text to the user's notes file.

| | |
|---|---|
| **Module** | `bob/tools/builtin/notes.py` |
| **Arguments** | `text` (required), `append` (optional, default `true`) — append to the file or replace it |
| **Storage** | `data/notes.md` (max ~20,000 characters) |
| **Use when** | The user asks Bob to remember something in their notes or jot something down. |

---

## memory_search

Searches Bob's long-term memory for facts about the user.

| | |
|---|---|
| **Module** | `bob/tools/builtin/recall.py` |
| **Arguments** | `query` (required), `limit` (optional, default 5, max 20) |
| **Use when** | The user asks about something Bob may have stored from past conversations (people, places, preferences). |

Requires the memory service to be loaded. Returns matching facts or a message that nothing was found.

---

## set_speech_mood

Sets how Bob's voice should sound for the rest of the current reply.

| | |
|---|---|
| **Module** | `bob/tools/builtin/mood.py` |
| **Arguments** | `mood` — one of `neutral`, `calm`, `warm`, `upbeat`, `excited`, `serious`, `sad`, `sorry`, `whisper`, `hurried` |
| **Use when** | The user's feelings or the news call for a different delivery tone. Call this before answering; do not say the mood name aloud. |

Adjusts TTS speed, pitch, gain, and pauses via the voice pipeline.

---

## list_speech_moods

Lists the voice moods Bob can use.

| | |
|---|---|
| **Module** | `bob/tools/builtin/mood.py` |
| **Arguments** | none |
| **Use when** | The user asks what moods or tones are available. |

---

## open_url

Opens a web page in the user's default browser.

| | |
|---|---|
| **Module** | `bob/tools/builtin/web.py` |
| **Arguments** | `url` — full `http://` or `https://` address |
| **Use when** | The user asks to open a specific website. |

Only full HTTP(S) URLs are accepted; invalid addresses return an error message to the model.
