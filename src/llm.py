"""One function to ask Claude for text, with a disk cache.

Every answer is saved in data/cache/<hash>.json. The hash comes from the
model, settings and prompt. If the same request comes again, the saved
answer is returned and nothing is paid (CLAUDE.md, section 7).
"""

import hashlib
import json

import anthropic
from langchain_anthropic import ChatAnthropic

from src import config

# "low" effort: the model thinks very little. Enough for short fake documents,
# and thinking tokens are billed as output tokens.
DEFAULT_EFFORT = "low"


def make_cache_key(model_name, system_prompt, user_prompt, max_tokens, effort):
    request = {
        "model": model_name, "system": system_prompt, "prompt": user_prompt,
        "max_tokens": max_tokens, "effort": effort,
    }
    # sort_keys makes the same request always give the same text, so the same hash.
    request_text = json.dumps(request, sort_keys=True)
    return hashlib.sha256(request_text.encode("utf-8")).hexdigest()


def read_cached_answer(cache_file):
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, encoding="utf-8") as file:
            return json.load(file)["text"]
    except (json.JSONDecodeError, KeyError):
        # A broken cache file (for example, the run stopped while writing) is a miss.
        return None


def ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort=DEFAULT_EFFORT):
    """Return the model's text answer. Use the cache when possible.

    Raises RuntimeError with a clear message when the call fails.
    """
    cache_key = make_cache_key(model_name, system_prompt, user_prompt, max_tokens, effort)
    cache_file = config.CACHE_DIR / f"{cache_key}.json"
    cached_text = read_cached_answer(cache_file)
    if cached_text is not None:
        return cached_text

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is empty. Set it in .env.")

    chat_model = ChatAnthropic(
        model=model_name,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        api_key=config.ANTHROPIC_API_KEY,
    )
    messages = [("system", system_prompt), ("human", user_prompt)]
    try:
        response = chat_model.invoke(messages)
    except anthropic.AuthenticationError:
        raise RuntimeError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic rate limit reached. Wait a minute and run again. Saved answers are kept.")
    except anthropic.APIConnectionError:
        raise RuntimeError("Cannot reach the Anthropic API. Check the internet connection.")
    except anthropic.APIStatusError as error:
        raise RuntimeError(f"Anthropic API error {error.status_code}: {error.message}")

    stop_reason = response.response_metadata.get("stop_reason")
    if stop_reason == "refusal":
        raise RuntimeError("The model declined this request.")
    if stop_reason == "max_tokens":
        # Do not cache a cut-off answer; it would be reused forever.
        raise RuntimeError(f"The answer was cut off at {max_tokens} tokens. Raise max_tokens.")

    answer_text = response.text.strip()
    if answer_text == "":
        raise RuntimeError("The model returned an empty answer.")

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    usage = response.usage_metadata or {}
    with open(cache_file, "w", encoding="utf-8") as file:
        json.dump({
            "model": model_name, "prompt": user_prompt, "text": answer_text,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }, file, indent=2)
    return answer_text
