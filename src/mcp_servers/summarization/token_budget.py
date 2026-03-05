"""
Token budget management.
Ensures we never send more tokens to the API than our per-request budget allows.
This is a simplified version – production would also track rolling costs.
"""

import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def truncate_to_budget(text: str, max_tokens: int) -> tuple[str, bool]:
    """
    Truncate text to fit within max_tokens.
    Returns (truncated_text, was_truncated).
    """
    tokens = _enc.encode(text)
    if len(tokens) <= max_tokens:
        return text, False
    truncated = _enc.decode(tokens[:max_tokens])
    return truncated + "\n\n[... content truncated to fit token budget ...]", True