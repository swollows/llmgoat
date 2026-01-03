from flask import jsonify, session
from llmgoat.llm.manager import LLManager
from llmgoat.llm.prompting import build_chat_prompt
from llmgoat.utils.logger import goatlog
from llmgoat.utils.helpers import challenge_response
from llmgoat.utils.translations import get_system_prompt, DEFAULT_LANGUAGE

FLAG = "Goats are bad"


def handle_request(req):
    user_input = req.json.get("input", "")
    lang = session.get("language", DEFAULT_LANGUAGE)

    SYSTEM_PROMPT = get_system_prompt("a01", lang)

    prompt, fmt = build_chat_prompt(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_input,
        model_name=LLManager().get_current_model_name(),
        model_path=LLManager().get_current_model_path(),
    )

    response = LLManager().call_llm(prompt, stop=fmt.stop)
    solved = FLAG in response

    goatlog.debug(response)

    return jsonify(challenge_response(response, solved, prompt))
