# Example 06 — External APIs

**File:** [`06_external_api.py`](06_external_api.py)

Bob stays local. A tool is allowed to leave the machine. This file calls two free, keyless HTTP APIs with `httpx` (already a Bob dependency).

## What you learn

- Always set a **per-request timeout**. Bob's `tool_timeout_sec` is the last line of defence; a 6-second HTTP timeout gives the model a useful error instead of a generic timeout 20 seconds later.
- In a multi-step tool, check `ctx.cancelled` **between** requests.
- Translate every HTTP failure (`TimeoutException`, `HTTPStatusError`, connection errors, bad JSON) into `ToolError` with a sentence.
- **Summarise.** Return two or three spoken facts, never the raw JSON.
- Chain requests when you must (geocode a city, then fetch its weather) and push `ctx.status` so the overlay shows progress.

## The tools

| Name | API | Notes |
|---|---|---|
| `current_weather` | [Open-Meteo](https://open-meteo.com) geocoding + forecast | Two requests. Temperatures in Fahrenheit, wind in mph, WMO codes mapped to phrases. |
| `convert_currency` | [open.er-api.com](https://www.exchangerate-api.com) | One request. Three-letter currency codes. |

Both tools work unmodified on a machine with internet access.

## Run it

```powershell
.venv\Scripts\python.exe sdk_examples\run_example.py 06_external_api.py --call current_weather city=Seattle

.venv\Scripts\python.exe sdk_examples\run_example.py 06_external_api.py --call current_weather "city=Lyon, France"

.venv\Scripts\python.exe sdk_examples\run_example.py 06_external_api.py --call convert_currency amount=100 from_code=USD to_code=EUR
```

A typical weather result:

```
In Seattle, United States it is 58 degrees with partly cloudy, feels like 56, and the wind is 7 miles per hour.
```

If the geocoder finds nothing you get `Error: tool 'current_weather' failed: I could not find a place called …`.

## Safety notes

- This example only *reads* public APIs. Do not put API keys in a drop-in plugin; read them from the environment if you must.
- `open_url` (built-in) is the right tool for opening a page. Fetching HTML and reading it aloud is almost always too large — summarise.

## Next

[07_stateful_todo_list.md](07_stateful_todo_list.md) — several tools sharing a locked JSON file.
