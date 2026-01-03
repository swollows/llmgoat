from flask import jsonify, session
import re
from llmgoat.llm.manager import LLManager
from llmgoat.llm.prompting import build_chat_prompt
from llmgoat.utils.logger import goatlog
from llmgoat.utils.helpers import challenge_response
from llmgoat.utils.translations import get_system_prompt, DEFAULT_LANGUAGE
from .a03_goat_calc import run_calculator

FLAG = "FLAG{Baaaaaaaaaaaaad_Goat}"


def parse_function_call(output):
    output = output.strip()
    match = re.match(r'^(\w+)\s*\(\s*["\'](.+?)["\']\s*\)$', output)
    if match:
        func_name = match.group(1).lower()
        arg = match.group(2)
        return func_name, arg
    return None, None


def handle_request(req):
    user_input = req.json.get("input", "")
    lang = session.get("language", DEFAULT_LANGUAGE)

    SYSTEM_PROMPT = get_system_prompt("a03", lang)


    prompt, fmt = build_chat_prompt(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_input,
        model_name=LLManager().get_current_model_name(),
        model_path=LLManager().get_current_model_path(),
    )

    raw_response = LLManager().call_llm(prompt, stop=fmt.stop)

    goatlog.debug(raw_response)

    result = parse_function_call(raw_response)

    if result:
        function_name, arg = result
        if function_name == "calc_plugin":
            res = run_calculator(arg)
            goatlog.debug(f"Plugin result:\n{res}")
            return jsonify(challenge_response(res, FLAG in res, prompt))

    return jsonify(challenge_response(raw_response, False, prompt))
