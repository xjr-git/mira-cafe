"""Scene directive protocol.

The character brain (LLM or scripted story) returns JSON:
{
  "say": "<text to be spoken>",
  "directives": [
    {"t": "emotion", "v": "shy"},
    {"t": "action",  "v": "stir_coffee"},
    {"t": "scene",   "v": "rain_stop"},
    {"t": "media",   "kind": "polaroid", "prompt": "..."},
    {"t": "goto",    "node": "reveal"}
  ]
}

Every directive type/value is validated against this whitelist before it
reaches the frontend, so a hallucinating model can never inject arbitrary
behavior into the scene."""

from typing import Any

EMOTIONS = {"neutral", "happy", "shy", "sad", "surprised"}
ACTIONS = {"stir_coffee", "look_camera", "gaze_window"}
SCENES = {"rain_stop"}
MEDIA_KINDS = {"polaroid"}


def validate(raw: Any) -> list[dict]:
    """Return a cleaned list of directives; unknown entries are dropped."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        t = d.get("t")
        v = d.get("v")
        if t == "emotion" and v in EMOTIONS:
            out.append({"t": "emotion", "v": v})
        elif t == "action" and v in ACTIONS:
            out.append({"t": "action", "v": v})
        elif t == "scene" and v in SCENES:
            out.append({"t": "scene", "v": v})
        elif t == "media" and d.get("kind") in MEDIA_KINDS:
            out.append({
                "t": "media",
                "kind": "polaroid",
                "prompt": str(d.get("prompt") or "")[:200],
            })
        elif t == "goto" and isinstance(v, str) and v in {"opening", "smalltalk", "confide", "reveal", "ending"}:
            out.append({"t": "goto", "v": v})
    return out
