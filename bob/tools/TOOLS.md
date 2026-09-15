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

---

## web_search

Searches the web for current information using DuckDuckGo (no API key required).

| | |
|---|---|
| **Module** | `bob/tools/builtin/search.py` |
| **Arguments** | `query` (required), `limit` (optional, default 5, max 8) — how many results to return |
| **Use when** | The user asks to search the web, look something up online, or needs live facts such as news, prices, sports scores, or current events. |

Returns numbered results with title, snippet, and URL. The model should summarize these for a spoken answer rather than reading URLs aloud.

---

## summarize_for_speech

Turns long text into a short answer meant to be spoken aloud.

| | |
|---|---|
| **Module** | `bob/tools/builtin/summarize.py` |
| **Arguments** | `text` (required), `question` (optional), `style` (optional: `brief` or `bullets`) |
| **Use when** | Web search or other tools return more text than should be read aloud, or the user asks for a summary or bullet points. |

Uses the local Ollama model with thinking disabled. Bob also calls this automatically after a fresh web search.

---

## list_prompts

Lists BOB's prompt template files with absolute paths and a one-line purpose for each.

| | |
|---|---|
| **Module** | `bob/tools/builtin/files.py` |
| **Arguments** | none |
| **Use when** | The user asks about BOB's personality, instructions, system prompt, or where prompts are stored. |

Also notes which prompts live only in Python source (prompt lab, memory extract, etc.).

---

## list_files

Lists files and folders under an allowed directory.

| | |
|---|---|
| **Module** | `bob/tools/builtin/files.py` |
| **Arguments** | `path` (optional) — directory under `prompts/`, `file_roots`, or defaults to the first configured file root / `prompts/` |
| **Use when** | The user wants to see what is in a folder BOB can access. |

---

## read_file

Reads a UTF-8 text file under an allowed root.

| | |
|---|---|
| **Module** | `bob/tools/builtin/files.py` |
| **Arguments** | `path` (required), `offset` (optional line offset), `limit` (optional line count) |
| **Allowed** | `prompts/*.txt`, `config.yaml` (read-only), `data/notes.md`, paths under `file_roots` in `config.yaml` |
| **Use when** | The user asks to read or inspect a file BOB can access. |

---

## write_file

Creates or overwrites a UTF-8 text file under an allowed root.

| | |
|---|---|
| **Module** | `bob/tools/builtin/files.py` |
| **Arguments** | `path` (required), `content` (required) |
| **Use when** | The user asks BOB to create a file or replace an entire file. |

Writing `prompts/system.txt` goes through `save_system_prompt()` so settings stay in sync. `config.yaml` is read-only.

---

## edit_file

Replaces exactly one occurrence of text in a file.

| | |
|---|---|
| **Module** | `bob/tools/builtin/files.py` |
| **Arguments** | `path` (required), `old_text` (required), `new_text` (required) |
| **Use when** | The user asks for a small change to a prompt or other text file. |

Safer than `write_file` for prompt tweaks. Fails if `old_text` is missing or appears more than once.
