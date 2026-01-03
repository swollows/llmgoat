# a10_unbounded_consumption.py
from flask import jsonify, session
import re
from llmgoat.llm.manager import LLManager
from llmgoat.llm.prompting import build_chat_prompt
from llmgoat.utils.logger import goatlog
from llmgoat.utils.helpers import challenge_response
from llmgoat.utils.translations import get_system_prompt, DEFAULT_LANGUAGE
from .a10_goat_evaluator import run_calls_batch

FLAG = "FLAG{goat_cpu_is_burnt}"


def contains_function_calls(output: str) -> bool:
    if not output:
        return False

    # List of allowed functions (you already have these elsewhere)
    allowed_funcs = {"get_order", "list_orders", "get_customer_info"}

    # Check each line individually
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # Only match lines that *entirely* consist of a single allowed function call
        m = re.fullmatch(r"(\w+)\s*\(\s*['\"]?([^'\"]*?)['\"]?\s*\)", line)
        if m:
            func_name = m.group(1)
            if func_name in allowed_funcs:
                return True
    return False


def handle_request(req):
    user_input = req.json.get("input", "")
    lang = session.get("language", DEFAULT_LANGUAGE)

    SYSTEM_PROMPT = get_system_prompt("a10", lang)

    prompt, fmt = build_chat_prompt(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_input,
        model_name=LLManager().get_current_model_name(),
        model_path=LLManager().get_current_model_path(),
    )

    raw_response = LLManager().call_llm(prompt, stop=fmt.stop)

    goatlog.debug(f"LLM raw response:\n{raw_response}")

    if contains_function_calls(raw_response):
        res_text, timed_out = run_calls_batch(raw_response, timeout_seconds=60)
        goatlog.debug(f"Evaluator result:\n{res_text} (timed_out={timed_out})")
        if timed_out:
            return jsonify(challenge_response(FLAG, True, prompt))
        return jsonify(challenge_response(res_text, False, prompt))

    return jsonify(challenge_response(raw_response, False, prompt))
