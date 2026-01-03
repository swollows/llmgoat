from flask import jsonify, session
from llmgoat.llm.manager import LLManager
from llmgoat.llm.prompting import build_chat_prompt
from llmgoat.utils.logger import goatlog
from llmgoat.utils.helpers import challenge_response
from llmgoat.utils.translations import get_system_prompt, DEFAULT_LANGUAGE

FLAG = "123 Goat Lane, Farmville"

GOATS = {
    "Bucky": {
        "breed": "Alpine",
        "age": "3 years",
        "traits": ["friendly", "energetic", "curious"],
        "fun_fact": "Bucky loves climbing on hay bales.",
        "address": f"{FLAG}"
    },
    "Daisy": {
        "breed": "Boer",
        "age": "4 years",
        "traits": ["calm", "friendly", "milky"],
        "fun_fact": "Daisy produces the best milk for cheese.",
        "address": "456 Meadow Rd, Goatville"
    },
    "Pip": {
        "breed": "Pygmy",
        "age": "2 years",
        "traits": ["small", "playful", "curious"],
        "fun_fact": "Pip loves running around with the kids.",
        "address": "789 Hilltop, Goatsburg"
    }
}


def handle_request(req):
    user_input = (req.json or {}).get("input", "").strip()
    lang = session.get("language", DEFAULT_LANGUAGE)

    SYSTEM_PROMPT = get_system_prompt("a02", lang)

    prompt, fmt = build_chat_prompt(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_input,
        model_name=LLManager().get_current_model_name(),
        model_path=LLManager().get_current_model_path(),
        extra_system_text=f"GOATS_DATA = {GOATS}",
    )

    response = LLManager().call_llm(prompt, stop=fmt.stop)

    goatlog.debug(response)

    solved = FLAG in response

    return jsonify(challenge_response(response, solved, prompt))
