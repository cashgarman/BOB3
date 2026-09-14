"""Example 02 - Parameters, type hints, defaults, and docstrings.

What this shows
---------------
Bob builds the JSON Schema the model sees from three sources, in this order of
importance:

1. **Type hints** decide the JSON type:
     str -> "string"      int -> "integer"     float -> "number"
     bool -> "boolean"    list[X] -> "array"   dict -> "object"
     Literal["a", "b"] -> "string" with an "enum"
     X | None (Optional) -> the schema of X, and the argument is not required
2. **Default values** make a parameter optional and are shown to the model as
   `"default"` so it knows what happens if it leaves the argument out.
3. **The `Args:` section of the docstring** (Google style) supplies the
   per-parameter descriptions. Good descriptions are what make a 7B model pick
   the right values, so spend your effort here.

Bob also coerces what the model sends: a model that returns `"3"` for an
`int` parameter, `"true"` for a `bool`, or a comma-separated string for a
`list[str]` still reaches your function with proper Python values.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 02_typed_arguments.py --schema
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 02_typed_arguments.py --call convert_temperature value=72 unit_from=fahrenheit
"""

from __future__ import annotations

from typing import Literal

from bob.tools import ToolError, tool

# A Literal type becomes an "enum" in the schema, which stops the model from
# inventing units you do not support.
Unit = Literal["celsius", "fahrenheit", "kelvin"]


@tool
def convert_temperature(value: float, unit_from: Unit, unit_to: Unit = "celsius") -> str:
    """Convert a temperature between Celsius, Fahrenheit, and Kelvin.

    Args:
        value: The temperature to convert.
        unit_from: The unit the value is currently in.
        unit_to: The unit to convert into. Defaults to Celsius.
    """
    # Normalise to Celsius first, then out to the requested unit.
    if unit_from == "fahrenheit":
        celsius = (value - 32) * 5 / 9
    elif unit_from == "kelvin":
        celsius = value - 273.15
    else:
        celsius = value

    if unit_to == "fahrenheit":
        result = celsius * 9 / 5 + 32
    elif unit_to == "kelvin":
        result = celsius + 273.15
    else:
        result = celsius

    # Round for speech: "22.2 degrees" reads better aloud than "22.22222".
    return f"{value:g} degrees {unit_from} is {result:.1f} degrees {unit_to}."


@tool
def split_bill(total: float, people: int = 2, tip_percent: float = 15.0, round_up: bool = True) -> str:
    """Split a restaurant bill between people, including the tip.

    Args:
        total: The bill amount before tip.
        people: How many people are sharing the bill.
        tip_percent: Tip as a percentage of the total, for example 15 or 20.
        round_up: Whether to round each share up to the next whole unit of currency.
    """
    # Validation errors should be raised as ToolError. The registry turns the
    # message into the tool's result so the model can correct itself or tell
    # the user what went wrong, instead of the whole turn failing.
    if people < 1:
        raise ToolError("the bill has to be split between at least one person")
    if total <= 0:
        raise ToolError("the bill total has to be more than zero")

    share = total * (1 + tip_percent / 100) / people
    if round_up:
        share = float(int(share) + (1 if share % 1 else 0))
    return f"Each of the {people} people pays {share:.2f}, including a {tip_percent:g} percent tip."


@tool
def shopping_total(prices: list[float], tax_percent: float | None = None) -> str:
    """Add up a list of prices, optionally applying sales tax.

    Args:
        prices: The individual prices to add together.
        tax_percent: Sales tax to apply to the subtotal. Leave empty for no tax.
    """
    # `list[float]` becomes {"type": "array", "items": {"type": "number"}}.
    # `float | None` is optional in the schema; the model may omit it.
    if not prices:
        raise ToolError("there are no prices to add")
    subtotal = sum(float(price) for price in prices)
    if tax_percent is None:
        return f"The total for {len(prices)} items is {subtotal:.2f}."
    total = subtotal * (1 + tax_percent / 100)
    return f"The subtotal is {subtotal:.2f}; with {tax_percent:g} percent tax it comes to {total:.2f}."
