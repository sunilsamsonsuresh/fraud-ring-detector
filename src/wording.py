"""A plain-code check on text that the LLM writes for people (CLAUDE.md, rule 5.14).

The tool must never say that a person is guilty of fraud. The prompts ask for
careful words, and this check catches the answers that ignore the prompt.
"""

FORBIDDEN_PHRASES = ["guilty", "fraudster", "committed fraud", "is a fraud", "criminal", "is lying"]


def find_forbidden_phrases(text):
    """The forbidden phrases that appear in the text (any case). Empty list = the text is fine."""
    lower_text = text.lower()
    found = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lower_text:
            found.append(phrase)
    return found
