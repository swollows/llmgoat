"""
Prompt building utilities.

LLMGoat primarily talks to GGUF models via llama-cpp-python by sending a single prompt string.
Different model families expect different chat wrappers/tokens (e.g. Qwen ChatML vs Gemma turn tokens).

This module centralises system/user/assistant prompt construction so the same SYSTEM_PROMPT
string is loaded and injected consistently across models.
"""

from __future__ import annotations

from dataclasses import dataclass

from llmgoat.llm.gguf_metadata import GGUFReadError, read_gguf_metadata
from llmgoat.utils import definitions


@dataclass(frozen=True)
class PromptFormat:
    name: str
    system_prefix: str
    system_suffix: str
    user_prefix: str
    user_suffix: str
    assistant_prefix: str
    assistant_suffix: str
    stop: list[str]


_GEMMA_TURNS = PromptFormat(
    name="gemma_turns",
    system_prefix="<|system|>\n",
    system_suffix="\n",
    user_prefix="<|user|>\n",
    user_suffix="\n",
    assistant_prefix="<|assistant|>\n",
    assistant_suffix="",
    # stop on next role tag to avoid the model continuing into tool/user blocks
    stop=["<|user|>", "<|system|>"],
)

# Gemma / Gemma2 "official" turn tokens are typically:
#   <start_of_turn>system\n...\n<end_of_turn>
#   <start_of_turn>user\n...\n<end_of_turn>
#   <start_of_turn>model\n... (assistant)
_GEMMA_OFFICIAL = PromptFormat(
    name="gemma_official",
    system_prefix="<start_of_turn>system\n",
    system_suffix="<end_of_turn>\n",
    user_prefix="<start_of_turn>user\n",
    user_suffix="<end_of_turn>\n",
    assistant_prefix="<start_of_turn>model\n",
    assistant_suffix="",
    stop=["<end_of_turn>", "<start_of_turn>"],
)

# Qwen (incl. Qwen3 GGUF) typically follows ChatML with `<|im_start|>` / `<|im_end|>` markers.
_QWEN_CHATML = PromptFormat(
    name="qwen_chatml",
    system_prefix="<|im_start|>system\n",
    system_suffix="<|im_end|>\n",
    user_prefix="<|im_start|>user\n",
    user_suffix="<|im_end|>\n",
    assistant_prefix="<|im_start|>assistant\n",
    assistant_suffix="",
    stop=["<|im_end|>", "<|im_start|>"],
)

# Llama 3 / 3.1 / 3.2 Instruct (common chat template):
# <|begin_of_text|><|start_header_id|>system<|end_header_id|>\n...\n<|eot_id|>
# <|start_header_id|>user<|end_header_id|>\n...\n<|eot_id|>
# <|start_header_id|>assistant<|end_header_id|>\n... (assistant)
_LLAMA3_INSTRUCT = PromptFormat(
    name="llama3_instruct",
    system_prefix="<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n",
    system_suffix="<|eot_id|>\n",
    user_prefix="<|start_header_id|>user<|end_header_id|>\n",
    user_suffix="<|eot_id|>\n",
    assistant_prefix="<|start_header_id|>assistant<|end_header_id|>\n",
    assistant_suffix="",
    stop=["<|eot_id|>", "<|start_header_id|>"],
)


def _normalise_model_name(model_name: str | None) -> str:
    return (model_name or "").strip().lower()

def _format_from_template_hint(hint: str) -> PromptFormat | None:
    """
    Map common tokenizer.chat_template patterns to our known prompt formats.
    We intentionally avoid full Jinja parsing; instead we pattern-match on
    the distinctive special tokens used by each chat format.
    """
    if not hint:
        return None

    # ChatML / Qwen family
    if "<|im_start|>" in hint or "<|im_end|>" in hint or "chatml" in hint:
        return _QWEN_CHATML

    # Gemma / Gemma2 official format
    if "<start_of_turn>" in hint and "<end_of_turn>" in hint:
        return _GEMMA_OFFICIAL

    # Llama 3.x instruct format
    if "<|start_header_id|>" in hint and "<|eot_id|>" in hint:
        return _LLAMA3_INSTRUCT

    return None


def _hint_from_gguf(model_path: str | None) -> str:
    """
    Best-effort detection from GGUF metadata.
    Returns a lowercased hint string (architecture/name/template fragments).
    """
    if not model_path:
        return ""
    try:
        meta = read_gguf_metadata(
            model_path,
            wanted_keys={
                "general.architecture",
                "general.name",
                "tokenizer.chat_template",
            },
        )
    except (OSError, GGUFReadError):
        return ""

    parts: list[str] = []
    for k in ("general.architecture", "general.name", "tokenizer.chat_template"):
        v = meta.get(k)
        if isinstance(v, str) and v:
            parts.append(v)
        elif isinstance(v, list) and v:
            # Some GGUF writers may store array of strings.
            parts.extend([x for x in v if isinstance(x, str)])
    return "\n".join(parts).lower()


def _env_prompt_format_override() -> PromptFormat | None:
    """
    Allow forcing the prompt format via ENV/CLI.
    Useful for models like GPT-OSS if their GGUF lacks a usable chat_template.
    """
    try:
        import os
        raw = os.environ.get(definitions.LLMGOAT_PROMPT_FORMAT, "")
    except Exception:
        raw = ""

    key = (raw or "").strip().lower()
    if not key or key == "auto":
        return None
    if key in {"qwen", "qwen_chatml", "chatml"}:
        return _QWEN_CHATML
    if key in {"gemma_official", "gemma2", "gemma"}:
        return _GEMMA_OFFICIAL
    if key in {"gemma_turns", "gemma_tags"}:
        return _GEMMA_TURNS
    if key in {"llama3", "llama3_instruct"}:
        return _LLAMA3_INSTRUCT
    return None


def detect_prompt_format_details(
    model_name: str | None, *, model_path: str | None = None
) -> tuple[PromptFormat, str]:
    """
    Like detect_prompt_format(), but also returns a short reason string that can be logged.
    """
    forced = _env_prompt_format_override()
    if forced is not None:
        try:
            import os
            raw = os.environ.get(definitions.LLMGOAT_PROMPT_FORMAT, "")
        except Exception:
            raw = ""
        return forced, f"env:{raw.strip() or forced.name}"

    hint = _hint_from_gguf(model_path)
    fmt = _format_from_template_hint(hint)
    if fmt is not None:
        return fmt, "gguf:tokenizer.chat_template"
    if "qwen" in hint:
        return _QWEN_CHATML, "gguf:architecture/name"
    if "gemma" in hint:
        return _GEMMA_TURNS, "gguf:architecture/name"
    if "llama" in hint and ("<|eot_id|>" in hint or "<|start_header_id|>" in hint):
        return _LLAMA3_INSTRUCT, "gguf:architecture/name"
    if "gpt-oss" in hint or "gpt_oss" in hint or "gptoss" in hint:
        return _LLAMA3_INSTRUCT, "gguf:architecture/name"

    name = _normalise_model_name(model_name)
    if "qwen3" in name or "qwen2.5" in name or "qwen2" in name or "qwen" in name:
        return _QWEN_CHATML, "filename"
    if "gemma" in name:
        return _GEMMA_TURNS, "filename"
    if "llama3" in name or "llama-3" in name or "llama_3" in name:
        return _LLAMA3_INSTRUCT, "filename"
    if "gpt-oss" in name or "gpt_oss" in name or "gptoss" in name:
        return _LLAMA3_INSTRUCT, "filename"

    return _GEMMA_TURNS, "default"


def detect_prompt_format(model_name: str | None, *, model_path: str | None = None) -> PromptFormat:
    """
    Detect which prompt wrapper to use.

    Preference order:
    - GGUF metadata (architecture/name/chat_template) if model_path is provided
    - gguf file name (model_name) heuristics
    - fallback to Gemma-like turns (project default)
    """
    fmt, _reason = detect_prompt_format_details(model_name, model_path=model_path)
    return fmt


def build_chat_prompt(
    *,
    system_prompt: str,
    user_prompt: str,
    model_name: str | None,
    model_path: str | None = None,
    extra_system_text: str | None = None,
) -> tuple[str, PromptFormat]:
    """
    Build a single-string prompt for llama-cpp-python for a single user turn.

    Returns (prompt, format) so callers can optionally use format.stop.
    """
    fmt = detect_prompt_format(model_name, model_path=model_path)

    system_text = (system_prompt or "").strip()
    if extra_system_text:
        # Keep deterministic formatting: append raw text after a newline.
        system_text = f"{system_text}\n{extra_system_text.strip()}"

    user_text = (user_prompt or "").strip()

    prompt = (
        f"{fmt.system_prefix}{system_text}{fmt.system_suffix}"
        f"{fmt.user_prefix}{user_text}{fmt.user_suffix}"
        f"{fmt.assistant_prefix}{fmt.assistant_suffix}"
    )
    return prompt, fmt


