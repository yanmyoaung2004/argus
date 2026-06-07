from __future__ import annotations

import logging
import re

from argus.shared.models import LLMProviderType

logger = logging.getLogger(__name__)

# Stopwords and filler patterns safe to strip from system prompts
STOPWORDS = {"the", "a", "an", "in", "on", "at", "for", "to", "of", "and", "or", "is", "are"}
COMPRESSIBLE_PROVIDERS = {LLMProviderType.OLLAMA, LLMProviderType.GROQ}


def compress_prompt(prompt: str, provider: LLMProviderType, min_ratio: float = 0.5) -> str:
    if provider not in COMPRESSIBLE_PROVIDERS:
        return prompt

    original_len = len(prompt)
    compressed = _remove_redundant_whitespace(prompt)
    compressed = _shorten_instructions(compressed)
    compressed = _remove_filler_words(compressed)
    compressed = _compress_json_examples(compressed)

    compressed_len = len(compressed)
    ratio = compressed_len / original_len if original_len > 0 else 1.0

    if ratio < min_ratio:
        target_len = int(original_len * min_ratio)
        compressed = compressed[:target_len]

    final_len = len(compressed)
    saved = original_len - final_len
    if saved > 0:
        logger.debug(
            "Prompt compressed",
            extra={"original": original_len, "compressed": final_len, "saved": saved, "ratio": f"{final_len / original_len:.1%}"},
        )

    return compressed


def compress_system_prompt(prompt: str, provider: LLMProviderType) -> str:
    return compress_prompt(prompt, provider)


def _remove_redundant_whitespace(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    return text.strip()


def _shorten_instructions(text: str) -> str:
    replacements = [
        (r"(?i)you are an? (expert |senior |experienced )?", "You are "),
        (r"(?i)please provide a detailed response", "Respond"),
        (r"(?i)please ensure that", ""),
        (r"(?i)make sure to", ""),
        (r"(?i)it is important to note that", ""),
        (r"(?i)it is worth mentioning that", ""),
        (r"(?i)in other words", "i.e."),
        (r"(?i)for example", "e.g."),
        (r"(?i)in order to", "to"),
        (r"(?i)as well as", "and"),
        (r"(?i)due to the fact that", "because"),
        (r"(?i)in the event that", "if"),
        (r"(?i)at this point in time", "now"),
        (r"(?i)in the context of", "in"),
        (r"(?i)with the exception of", "except"),
        (r"(?i)a number of", "some"),
        (r"(?i)the majority of", "most"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _remove_filler_words(text: str) -> str:
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        words = line.split()
        filtered = [w for w in words if w.lower() not in STOPWORDS or len(line) < 50]
        cleaned.append(" ".join(filtered) if filtered else line)
    return "\n".join(cleaned)


def _compress_json_examples(text: str) -> str:
    text = re.sub(r"\s+(\{)", r"\1", text)
    text = re.sub(r"(\})\s+", r"\1", text)
    text = re.sub(r'"\s*:\s*', '": ', text)
    text = re.sub(r'\s*,\s*"', ', "', text)
    return text


def estimate_tokens(text: str) -> int:
    return len(text) // 4
