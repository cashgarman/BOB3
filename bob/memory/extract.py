from __future__ import annotations

import json
import re
from typing import Any

EXTRACT_PROMPT = """\
Extract lasting facts about the user from this voice turn.
Return JSON only: {"facts":[{"text":"...","entities":[{"name":"...","type":"person|place|thing|pref"}],"relations":[{"src":"user","rel":"likes|lives_in|called|works_at|owns|prefers","dst":"..."}]}]}
Rules:
- Only durable personal facts (name, people, places, tools, preferences).
- Skip chit-chat, time, weather, one-off questions, and assistant filler.
- If nothing lasting, return {"facts":[]}.
- text must be a short standalone sentence.
"""


def parse_facts(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        return []
    cleaned = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        body = str(fact.get("text") or "").strip()
        if len(body) < 8:
            continue
        ents = fact.get("entities") if isinstance(fact.get("entities"), list) else []
        rels = fact.get("relations") if isinstance(fact.get("relations"), list) else []
        cleaned.append(
            {
                "text": body,
                "entities": [e for e in ents if isinstance(e, dict) and e.get("name")],
                "relations": [r for r in rels if isinstance(r, dict) and r.get("dst")],
            }
        )
    return cleaned
