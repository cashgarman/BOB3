"""Example 06 - Calling web APIs from a tool.

What this shows
---------------
Tools can reach the internet; Bob itself stays local, only the tool's own
requests leave the machine. Both APIs below are free and need no key:

* Open-Meteo for weather (two chained requests: geocode the city, then fetch
  the forecast for its coordinates).
* open.er-api.com for exchange rates (a single request).

Patterns worth copying
----------------------
* **Always set a timeout** on HTTP calls. Bob's own tool timeout is the last
  line of defence; a tight per-request timeout gives the model a useful error
  quickly instead of a generic "timed out" 20 seconds later.
* **Check `ctx.cancelled` between requests** in multi-step tools.
* **Translate API errors into `ToolError`** with a sentence, not a stack trace.
* **Summarise the response.** Return two or three spoken facts, never the raw
  JSON. The model will otherwise try to read numbers it does not understand.
* `httpx` is already a Bob dependency (it talks to Ollama), so no new install.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 06_external_api.py --call current_weather city=Seattle
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 06_external_api.py --call convert_currency amount=100 from_code=USD to_code=EUR
"""

from __future__ import annotations

import httpx

from bob.tools import ToolContext, ToolError, tool

# Short per-request timeout: slow answers are worse than no answers in a
# voice conversation.
HTTP_TIMEOUT = httpx.Timeout(6.0)

# WMO weather interpretation codes, condensed to phrases that sound natural.
_WEATHER_CODES = {
    0: "clear skies",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "icy fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "heavy showers",
    82: "violent showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "severe thunderstorms with hail",
}


def _get_json(client: httpx.Client, url: str, params: dict) -> dict:
    """Fetch JSON or raise a ToolError the model can relay."""
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException as exc:
        raise ToolError("the weather service took too long to answer") from exc
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"the service answered with HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"could not reach the service: {exc}") from exc
    except ValueError as exc:
        raise ToolError("the service returned something that was not JSON") from exc


@tool
def current_weather(city: str, *, ctx: ToolContext) -> str:
    """Get the current weather for a city anywhere in the world.

    Args:
        city: The city name, optionally with a country, for example "Lyon, France".
    """
    place = city.strip()
    if not place:
        raise ToolError("tell me which city to look up")

    with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": "bob-voice-assistant"}) as client:
        # Step 1: geocode the city name to coordinates.
        ctx.status(f"finding {place}")
        geo = _get_json(
            client,
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": place.split(",")[0], "count": 1, "language": "en", "format": "json"},
        )
        results = geo.get("results") or []
        if not results:
            raise ToolError(f"I could not find a place called {place}")
        hit = results[0]
        label = ", ".join(part for part in (hit.get("name"), hit.get("country")) if part)

        # A multi-request tool should notice cancellation between requests.
        if ctx.cancelled:
            return "Cancelled."

        # Step 2: fetch the current conditions for those coordinates.
        ctx.status(f"weather for {label}")
        forecast = _get_json(
            client,
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": hit["latitude"],
                "longitude": hit["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
            },
        )

    current = forecast.get("current") or {}
    condition = _WEATHER_CODES.get(int(current.get("weather_code", -1)), "mixed conditions")
    temperature = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    wind = current.get("wind_speed_10m")
    if temperature is None:
        raise ToolError(f"no current conditions were available for {label}")

    # Three facts, one sentence: exactly the size of answer a voice assistant
    # should speak.
    return (
        f"In {label} it is {temperature:.0f} degrees with {condition}, "
        f"feels like {feels:.0f}, and the wind is {wind:.0f} miles per hour."
    )


@tool
def convert_currency(amount: float, from_code: str, to_code: str) -> str:
    """Convert an amount of money between currencies using today's exchange rate.

    Args:
        amount: How much money to convert.
        from_code: Three-letter code of the currency you have, for example USD.
        to_code: Three-letter code of the currency you want, for example EUR.
    """
    source = from_code.strip().upper()
    target = to_code.strip().upper()
    if len(source) != 3 or len(target) != 3:
        raise ToolError("currency codes have to be three letters, like USD or EUR")

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        data = _get_json(client, f"https://open.er-api.com/v6/latest/{source}", {})

    rates = data.get("rates") or {}
    rate = rates.get(target)
    if data.get("result") != "success" or rate is None:
        raise ToolError(f"I do not have a rate from {source} to {target}")
    converted = amount * float(rate)
    return f"{amount:,.2f} {source} is about {converted:,.2f} {target} at a rate of {rate:.4f}."
