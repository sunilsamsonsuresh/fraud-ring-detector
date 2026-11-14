"""Ask Claude. Every LLM call of the project goes through this file.

ask_llm: one question, one text answer, cached. The data pipeline uses it.
ask_llm_with_tools: a conversation with the strong model, maybe with tools. The chat uses it. Not cached.

Every answer of ask_llm is saved in data/cache/<hash>.json. The hash comes from the model, the settings and the
prompt. If the same request comes again, the saved answer is returned and nothing is paid (CLAUDE.md,
section 7). Thus, loading the PDFs again costs nothing.

If a request is not in the cache and ANTHROPIC_API_KEY is empty, ask_llm stops with a clear message.
"""

import hashlib
import json

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage

from src import config

# "low" effort: the model thinks very little. It is enough for short fake documents, and thinking
# tokens are billed as output tokens.
DEFAULT_EFFORT = "low"


def make_cache_key(model_name, system_prompt, user_prompt, max_tokens, effort):
    request = {
        "model": model_name,
        "system": system_prompt,
        "prompt": user_prompt,
        "max_tokens": max_tokens,
        "effort": effort,
    }
    # sort_keys makes the same request always give the same text, and so the same hash.
    request_text = json.dumps(request, sort_keys=True)
    return hashlib.sha256(request_text.encode("utf-8")).hexdigest()


def read_cached_answer(cache_file):
    """The saved text, or None. A broken file (for example, the run stopped while writing) is a miss."""
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, encoding="utf-8") as file:
            return json.load(file)["text"]
    except (json.JSONDecodeError, KeyError):
        return None


def call_model(chat_model, messages, max_tokens):
    """Call the model one time. Turn API errors into RuntimeError with a clear message."""
    try:
        response = chat_model.invoke(messages)
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in .env."
        )
    except anthropic.RateLimitError:
        raise RuntimeError(
            "Anthropic rate limit reached. Wait a minute and run again. Saved answers are kept."
        )
    except anthropic.APIConnectionError:
        raise RuntimeError(
            "Cannot reach the Anthropic API. Check the internet connection."
        )
    except anthropic.APIStatusError as error:
        raise RuntimeError(f"Anthropic API error {error.status_code}: {error.message}")
    stop_reason = response.response_metadata.get("stop_reason")
    if stop_reason == "refusal":
        raise RuntimeError("The model declined this request.")
    if stop_reason == "max_tokens":
        # Do not save a cut-off answer. It would be reused forever.
        raise RuntimeError(
            f"The answer was cut off at {max_tokens} tokens. Raise max_tokens."
        )
    return response


def ask_llm(
    user_prompt, model_name, system_prompt, max_tokens=1500, effort=DEFAULT_EFFORT
):
    """Return the text answer of the model. Use the cache when possible.

    Raises RuntimeError with a clear message when the call fails."""
    cache_key = make_cache_key(
        model_name, system_prompt, user_prompt, max_tokens, effort
    )
    cache_file = config.CACHE_DIR / f"{cache_key}.json"
    cached_text = read_cached_answer(cache_file)
    if cached_text is not None:
        return cached_text

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is empty and this request is not in the cache. Set the key in .env."
        )

    chat_model = ChatAnthropic(
        model=model_name,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        api_key=config.ANTHROPIC_API_KEY,
    )
    response = call_model(
        chat_model, [("system", system_prompt), ("human", user_prompt)], max_tokens
    )
    answer_text = response.text.strip()
    if answer_text == "":
        raise RuntimeError("The model returned an empty answer.")

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    usage = response.usage_metadata or {}
    with open(cache_file, "w", encoding="utf-8") as file:
        json.dump(
            {
                "model": model_name,
                "prompt": user_prompt,
                "text": answer_text,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            file,
            indent=2,
        )
    return answer_text


def ask_llm_with_tools(
    messages,
    tools,
    system_prompt,
    one_tool_at_a_time=False,
    max_tokens=8000,
    effort=DEFAULT_EFFORT,
):
    """Send a conversation (and maybe a tool list) to the STRONG model. Return its answer as an AIMessage.

    The answer has .tool_calls (the tools the model wants, maybe none) and .text (its words).
    tools: a list of {"name", "description", "input_schema"} dicts. An empty list means: no tools, only words.
    one_tool_at_a_time=True: the model may ask for at most one tool per answer (the planner uses it).
    The chat is NOT cached: every message is a new question. Raises RuntimeError with a clear message."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is empty. Set the key in .env.")
    chat_model = ChatAnthropic(
        model=config.STRONG_MODEL_NAME,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        api_key=config.ANTHROPIC_API_KEY,
    )
    if tools:
        chat_model = chat_model.bind_tools(
            tools, parallel_tool_calls=not one_tool_at_a_time
        )
    response = call_model(
        chat_model, [SystemMessage(system_prompt)] + list(messages), max_tokens
    )
    if not response.tool_calls and response.text.strip() == "":
        raise RuntimeError("The model returned an empty answer.")
    return response
