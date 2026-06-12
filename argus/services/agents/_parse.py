from __future__ import annotations

import json
import re
from typing import Any


def _strip_code_fences(text: str) -> str:
    text = re.sub(r"(?s)^\s*```(?:json)?\s*\n?", "", text)
    text = re.sub(r"(?s)\n?\s*```\s*$", "", text)
    return text


def _balanced_bracket_match(text: str, open_b: str, close_b: str) -> tuple[int, int] | None:
    start = text.find(open_b)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_b:
            depth += 1
        elif text[i] == close_b:
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None


def extract_json_array(text: str) -> list[dict[str, Any]]:
    text = _strip_code_fences(text.strip())
    span = _balanced_bracket_match(text, "[", "]")
    if span:
        text = text[span[0] : span[1]]
    return json.loads(text)


def extract_json_object(text: str) -> dict[str, Any]:
    text = _strip_code_fences(text.strip())
    span = _balanced_bracket_match(text, "{", "}")
    if span:
        text = text[span[0] : span[1]]
    return json.loads(text)
