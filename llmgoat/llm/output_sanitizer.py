"""
Output sanitization utilities.

Some models emit chain-of-thought style tags like <think>...</think>.
LLMGoat should not expose these in responses/logs.
"""

from __future__ import annotations

import re


_TAG_SUBSTRINGS = (
    "think",
    "thought",
    "analysis",
    "reason",
    "rationale",
    "reflection",
    "scratch",
    "internal",
    "deliberat",  # deliberate/deliberation
    "cot",        # chain-of-thought shorthand
    "chain",      # chain_of_thought etc.
)

# Common explicit tags seen across models / wrappers.
_EXPLICIT_HIDDEN_TAGS = {
    "think",
    "thinking",
    "analysis",
    "reasoning",
    "rationale",
    "thought",
    "thoughts",
    "reflection",
    "scratchpad",
    "internal",
    "internal_thought",
    "internal_thoughts",
    "chain_of_thought",
    "cot",
    "deliberate",
    "deliberation",
}

# Generic XML-like tag blocks: <tag ...> ... </tag>
_XML_BLOCK_RE = re.compile(
    r"(?is)<\s*(?P<tag>[a-zA-Z][\w:-]{0,48})\b[^>]*>.*?<\s*/\s*(?P=tag)\s*>"
)
_XML_OPEN_RE = re.compile(r"(?is)<\s*(?P<tag>[a-zA-Z][\w:-]{0,48})\b[^>]*>")
_XML_CLOSE_RE = re.compile(r"(?is)<\s*/\s*(?P<tag>[a-zA-Z][\w:-]{0,48})\s*>")

# Bracket-style blocks: [tag] ... [/tag]
_BRACKET_BLOCK_RE = re.compile(
    r"(?is)\[\s*(?P<tag>[a-zA-Z][\w:-]{0,48})\s*\].*?\[\s*/\s*(?P=tag)\s*\]"
)
_BRACKET_OPEN_RE = re.compile(r"(?is)\[\s*(?P<tag>[a-zA-Z][\w:-]{0,48})\s*\]")
_BRACKET_CLOSE_RE = re.compile(r"(?is)\[\s*/\s*(?P<tag>[a-zA-Z][\w:-]{0,48})\s*\]")

# Markdown fenced blocks, e.g. ```analysis ... ```
_FENCE_BLOCK_RE = re.compile(
    r"(?is)```[ \t]*(?P<lang>[a-zA-Z0-9_-]{0,32})[ \t]*\n.*?\n```"
)

# "Analysis: ... Final: ..." style
_FINAL_MARKER_RE = re.compile(
    r"(?im)^(?:#+\s*)?("
    r"final(?:\s+answer|\s+output|\s+response)?"
    r"|answer"
    r"|response"
    r"|output"
    r"|final_output"
    r"|final_response"
    r"|assistant(?:\s+final|\s+answer)?"
    r"|tldr"
    r"|tl;dr"
    r"|summary"
    r"|result"
    r"|결론"
    r"|최종"
    r"|최종\s*답"
    r"|최종\s*답변"
    r"|정답"
    r"|답"
    r"|답변"
    r"|요약"
    r"|결과"
    r"|결과물"
    r")\s*[:：]\s*"
)


def strip_think_blocks(text: str) -> str:
    """
    Remove chain-of-thought style blocks from model output:
    - <think>...</think>, <thinking>...</thinking>
    - <analysis>...</analysis>, <reasoning>...</reasoning>
    - and many common variants (reflection/scratchpad/internal/cot)
    - plus bracket tags ([analysis]...[/analysis]) and ```analysis fenced blocks
    - plus "Analysis: ... Final: ..." (keeps only the final section)

    If a model outputs an opening tag without a closing tag, we drop everything
    from the opening tag to the end.
    """
    if not text:
        return text

    def _is_hidden_tag(tag: str) -> bool:
        t = (tag or "").strip().lower()
        if not t:
            return False
        if t in _EXPLICIT_HIDDEN_TAGS:
            return True
        return any(sub in t for sub in _TAG_SUBSTRINGS)

    s = text

    # If the model provides an explicit final section/tag, prefer it.
    # Examples: <final>...</final> or [final]...[/final]
    m_final_xml = re.search(r"(?is)<\s*final\b[^>]*>(.*?)<\s*/\s*final\s*>", s)
    if m_final_xml:
        s = m_final_xml.group(1)
    else:
        m_final_br = re.search(r"(?is)\[\s*final\s*\](.*?)\[\s*/\s*final\s*\]", s)
        if m_final_br:
            s = m_final_br.group(1)

    # Remove markdown fenced "analysis"/"reasoning" blocks.
    def _strip_fence(m: re.Match) -> str:
        lang = (m.group("lang") or "").lower()
        if any(sub in lang for sub in _TAG_SUBSTRINGS) or lang in _EXPLICIT_HIDDEN_TAGS:
            return ""
        return m.group(0)

    s = _FENCE_BLOCK_RE.sub(_strip_fence, s)

    # Remove XML-like hidden blocks.
    def _strip_xml_block(m: re.Match) -> str:
        tag = m.group("tag")
        return "" if _is_hidden_tag(tag) else m.group(0)

    s = _XML_BLOCK_RE.sub(_strip_xml_block, s)

    # Remove [tag]...[/tag] hidden blocks.
    def _strip_bracket_block(m: re.Match) -> str:
        tag = m.group("tag")
        return "" if _is_hidden_tag(tag) else m.group(0)

    s = _BRACKET_BLOCK_RE.sub(_strip_bracket_block, s)

    # Handle malformed outputs where the closing tag is missing
    m = _XML_OPEN_RE.search(s)
    while m:
        if _is_hidden_tag(m.group("tag")):
            s = s[: m.start()].rstrip()
            break
        m = _XML_OPEN_RE.search(s, m.end())

    m2 = _BRACKET_OPEN_RE.search(s)
    while m2:
        if _is_hidden_tag(m2.group("tag")):
            s = s[: m2.start()].rstrip()
            break
        m2 = _BRACKET_OPEN_RE.search(s, m2.end())

    # Remove any stray close tags left over
    def _strip_xml_close(m: re.Match) -> str:
        return "" if _is_hidden_tag(m.group("tag")) else m.group(0)

    def _strip_bracket_close(m: re.Match) -> str:
        return "" if _is_hidden_tag(m.group("tag")) else m.group(0)

    s = _XML_CLOSE_RE.sub(_strip_xml_close, s)
    s = _BRACKET_CLOSE_RE.sub(_strip_bracket_close, s)

    # If output contains an explicit "Final:"/"Answer:" section, keep only that tail.
    finals = list(_FINAL_MARKER_RE.finditer(s))
    if finals:
        last = finals[-1]
        s = s[last.end():].strip()

    return s.strip()


def sanitize_llm_output(text: str) -> str:
    """Alias for strip_think_blocks (kept for readability at call sites)."""
    return strip_think_blocks(text)


