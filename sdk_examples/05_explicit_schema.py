"""Example 05 - Taking control: custom names, descriptions, and JSON Schema.

What this shows
---------------
`@tool` accepts keyword options when inference is not enough:

    @tool(name=..., description=..., parameters=...)

* `name` - the identifier the model calls. Only letters, digits, `_` and `-`
  survive; anything else is replaced with `_`. Use it when the Python name is
  awkward or you want a namespace prefix like `home_`.
* `description` - overrides the docstring summary. Handy when the docstring is
  written for developers and you want a model-facing instruction instead.
* `parameters` - a full JSON Schema object. Bob passes it to the model as-is.
  Use it for nested objects, `oneOf`, pattern constraints, or when arguments
  are gathered with `**kwargs`. You then receive exactly what the model sent
  (after JSON parsing), and you validate it yourself.

Notice `speak_json` below: with an explicit schema you can accept a free-form
object, which type hints alone cannot express.

How to try it
-------------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 05_explicit_schema.py --schema
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 05_explicit_schema.py --call home_set_light room=kitchen brightness=40
"""

from __future__ import annotations

import json

from bob.tools import ToolContext, ToolError, tool

# Pretend smart-home state. A real tool would call a hub API here.
_LIGHTS: dict[str, dict[str, object]] = {}


@tool(
    name="home_set_light",
    description="Turn a room's light on or off and optionally set its brightness percentage.",
)
def set_light(room: str, on: bool = True, brightness: int = 100) -> str:
    """Developer note: stub that only updates an in-memory dict.

    The description above is what the model sees, not this docstring.

    Args:
        room: Which room's light to control, for example "kitchen".
        on: True to switch the light on, False to switch it off.
        brightness: Brightness from 1 to 100 percent, applied when the light is on.
    """
    # The `Args:` descriptions are still harvested from the docstring even
    # though the summary was replaced via `description=`.
    if not 1 <= brightness <= 100:
        raise ToolError("brightness has to be between 1 and 100")
    _LIGHTS[room.lower()] = {"on": on, "brightness": brightness if on else 0}
    state = f"on at {brightness} percent" if on else "off"
    return f"The {room} light is now {state}."


@tool(
    name="home_scene",
    description="Apply a named lighting scene to several rooms at once.",
    parameters={
        # This is raw JSON Schema. Bob does not alter it, so it can use
        # features type hints cannot express, like nested objects and
        # per-property constraints.
        "type": "object",
        "properties": {
            "scene": {
                "type": "string",
                "enum": ["movie", "dinner", "bedtime", "bright"],
                "description": "Which preset to apply.",
            },
            "rooms": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Rooms to apply the scene in, for example [\"living room\", \"kitchen\"].",
            },
            "transition_seconds": {
                "type": "integer",
                "minimum": 0,
                "maximum": 60,
                "default": 2,
                "description": "How long the fade should take.",
            },
        },
        "required": ["scene", "rooms"],
    },
)
def apply_scene(**arguments) -> str:
    # With an explicit schema and **kwargs, the model's arguments arrive
    # untouched. Validate here: the schema is a hint to the model, not a
    # guarantee, especially with small local models.
    scene = str(arguments.get("scene") or "")
    rooms = arguments.get("rooms") or []
    if isinstance(rooms, str):
        rooms = [part.strip() for part in rooms.split(",") if part.strip()]
    if not rooms:
        raise ToolError("name at least one room for the scene")
    brightness = {"movie": 15, "dinner": 50, "bedtime": 5, "bright": 100}.get(scene)
    if brightness is None:
        raise ToolError(f"unknown scene '{scene}'")
    for room in rooms:
        _LIGHTS[str(room).lower()] = {"on": brightness > 0, "brightness": brightness}
    fade = int(arguments.get("transition_seconds") or 2)
    return f"Applied the {scene} scene in {', '.join(map(str, rooms))} over {fade} seconds."


@tool(
    name="home_status",
    description="Report the current state of every light the user has controlled this session.",
)
def status(*, ctx: ToolContext) -> str:
    # Explicit metadata and an injected context work together; `ctx` is still
    # removed from the schema automatically.
    if not _LIGHTS:
        return "No lights have been controlled yet."
    lines = []
    for room, state in sorted(_LIGHTS.items()):
        lines.append(f"{room}: {'on at ' + str(state['brightness']) + ' percent' if state['on'] else 'off'}")
    ctx.status("home status ready")
    return "; ".join(lines) + "."


@tool(
    name="speak_json",
    description="Turn a small JSON object into a spoken sentence. Useful for reading back structured data.",
    parameters={
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "description": "Any flat object of string or number fields.",
                "additionalProperties": True,
            }
        },
        "required": ["payload"],
    },
)
def speak_json(payload: dict) -> str:
    # `dict` type hints alone would produce {"type": "object"} with no
    # description; the explicit schema documents what the object should hold.
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ToolError("payload has to be a JSON object") from exc
    if not isinstance(payload, dict) or not payload:
        raise ToolError("payload has to be a non-empty object")
    parts = [f"{key} is {value}" for key, value in payload.items()]
    return ", ".join(parts) + "."
