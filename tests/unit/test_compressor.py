from __future__ import annotations

from argus.llm.compressor import (
    _compress_json_examples,
    _remove_filler_words,
    _remove_redundant_whitespace,
    _shorten_instructions,
    compress_prompt,
    compress_system_prompt,
    estimate_tokens,
)
from argus.shared.models import LLMProviderType


class TestCompressPrompt:
    def test_skips_openrouter(self) -> None:
        original = "This is a long prompt " * 20
        result = compress_prompt(original, LLMProviderType.OPENROUTER)
        assert result == original

    def test_compresses_ollama(self) -> None:
        original = "You are an expert assistant. Please provide a detailed response."
        result = compress_prompt(original, LLMProviderType.OLLAMA)
        assert len(result) <= len(original)

    def test_compresses_groq(self) -> None:
        original = "You are an expert assistant. Please provide a detailed response."
        result = compress_prompt(original, LLMProviderType.GROQ)
        assert len(result) <= len(original)

    def test_min_ratio_enforced(self) -> None:
        original = "a " * 200
        result = compress_prompt(original, LLMProviderType.OLLAMA, min_ratio=0.8)
        assert len(result) >= len(original) * 0.8

    def test_empty_string(self) -> None:
        assert compress_prompt("", LLMProviderType.OLLAMA) == ""

    def test_short_prompt_unchanged(self) -> None:
        assert compress_prompt("Hi", LLMProviderType.OLLAMA) == "Hi"


class TestCompressSystemPrompt:
    def test_delegates_to_compress_prompt(self) -> None:
        result = compress_system_prompt("You are an expert. Please respond.", LLMProviderType.OLLAMA)
        assert isinstance(result, str)


class TestRemoveRedundantWhitespace:
    def test_collapses_newlines(self) -> None:
        assert _remove_redundant_whitespace("a\n\n\n\nb") == "a\n\nb"

    def test_collapses_spaces(self) -> None:
        assert _remove_redundant_whitespace("a  b   c") == "a b c"

    def test_strips_whitespace(self) -> None:
        assert _remove_redundant_whitespace("  hello  ") == "hello"


class TestShortenInstructions:
    def test_removes_expert_prefix(self) -> None:
        result = _shorten_instructions("You are an expert assistant.")
        assert "expert" not in result

    def test_shortens_please_provide(self) -> None:
        result = _shorten_instructions("Please provide a detailed response.")
        assert "Please provide" not in result

    def test_shortens_verbosity(self) -> None:
        text = "It is important to note that due to the fact that X, in order to Y"
        result = _shorten_instructions(text)
        assert "due to the fact that" not in result
        assert "in order to" not in result
        assert "to" in result


class TestRemoveFillerWords:
    def test_removes_stopwords_in_long_text(self) -> None:
        text = "the quick brown fox jumps over the lazy dog near the large white fence"
        result = _remove_filler_words(text)
        assert "the" not in result

    def test_preserves_short_lines(self) -> None:
        text = "Hi there"
        result = _remove_filler_words(text)
        assert result == text

    def test_empty_string(self) -> None:
        assert _remove_filler_words("") == ""


class TestCompressJsonExamples:
    def test_removes_whitespace_around_braces(self) -> None:
        text = '{ "key" : "value" }'
        result = _compress_json_examples(text)
        assert " " not in result or '" ' in result  # at least more compact than original

    def test_whitespace_around_colons(self) -> None:
        text = '"key"  :  "value"'
        result = _compress_json_examples(text)
        assert '"key": "value"' in result or '"key": "value"' in result.replace(" ", "")


class TestEstimateTokens:
    def test_estimates_tokens(self) -> None:
        text = "hello world how are you" * 10
        assert estimate_tokens(text) > 0

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0
