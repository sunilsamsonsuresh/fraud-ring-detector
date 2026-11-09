"""Plain code checks every value of the route before anything runs (PLAN-v2.md V14, CLAUDE.md rule 10).

check_route returns (parameters, message):
- parameters: the checked values for the tool of the intent.
- message:    a fixed text when nothing may run: the claim is not found, the tool must ask
              which claim, the rule does not exist, or the question is out of scope.
A missing claim ID is taken from the chat's current case. Never guessed.
"""

import re

from src.agents.question_router import PORTFOLIO_VIEWS
from src.graph import queries
from src.scoring.rules_catalog import RULES_BY_ID

CLAIM_ID_PATTERN = re.compile(r"^C-\d{4}$")
CLAIM_INTENTS = ["investigate_claim", "explain_score", "search_documents", "score_history"]
DEFAULT_PORTFOLIO_LIMIT = 10
MAX_PORTFOLIO_LIMIT = 25
MIN_NAME_CHARACTERS = 3
MAX_TEXT_CHARACTERS = 200

ASK_WHICH_CLAIM = "Which claim do you mean? Give a claim ID, for example C-1026."
OUT_OF_SCOPE = ("I can answer questions about the claims in this tool: is a claim suspicious, why it has its "
                "score, what it is linked to, what its documents say, how its score changed, the riskiest "
                "claims, and what a rule means. Example: 'Why is C-1026 Medium?'")


def claim_exists(driver, claim_id):
    records, _, _ = driver.execute_query(queries.CLAIM_EXISTS, claim_id=claim_id)
    return bool(records)


def checked_claim_id(driver, route, current_case):
    """Return (claim ID, message). The ID comes from the question, else from the current case."""
    claim_id = route["claim_id"].upper()
    if not claim_id:
        if not current_case:
            return None, ASK_WHICH_CLAIM
        claim_id = current_case
    if not CLAIM_ID_PATTERN.match(claim_id):
        return None, f"'{route['claim_id']}' is not a claim ID. A claim ID looks like C-1026."
    if not claim_exists(driver, claim_id):
        return None, f"Claim {claim_id} was not found in the graph."
    return claim_id, None


def phone_end_of(text):
    """The digits of a phone number as stored ("713-555-0142"), or its last 7 digits ("555-0142"). "" if neither."""
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return ""


def check_route(driver, route, question, current_case):
    intent = route["intent"]
    if intent == "unclear_or_out_of_scope":
        return {}, OUT_OF_SCOPE

    if intent in CLAIM_INTENTS:
        claim_id, message = checked_claim_id(driver, route, current_case)
        if message:
            return {}, message
        parameters = {"claim_id": claim_id}
        if intent == "search_documents":
            # The topic is only turned into an embedding for the text search. It never runs as a query.
            parameters["topic"] = (route["topic"] or question)[:MAX_TEXT_CHARACTERS]
        return parameters, None

    if intent == "explore_connections":
        if route["phone"]:
            phone_end = phone_end_of(route["phone"])
            if not phone_end:
                return {}, f"'{route['phone']}' is not a phone number. Give 7 or 10 digits."
            return {"phone_end": phone_end}, None
        if route["name"]:
            name = route["name"][:MAX_TEXT_CHARACTERS]
            if len(name) < MIN_NAME_CHARACTERS:
                return {}, f"The name '{name}' is too short. Give at least {MIN_NAME_CHARACTERS} letters."
            return {"name": name}, None
        claim_id, message = checked_claim_id(driver, route, current_case)
        if message:
            return {}, message
        return {"claim_id": claim_id}, None

    if intent == "rule_lookup":
        rule_id = route["rule_id"].upper().replace(" ", "")
        if rule_id not in RULES_BY_ID:
            return {}, (f"Rule '{route['rule_id']}' was not found. Rule IDs look like BF-1. "
                        "Run: python main.py show-rules")
        return {"rule_id": rule_id}, None

    # portfolio_overview
    view = route["view"] if route["view"] in PORTFOLIO_VIEWS else "top_claims"
    limit = route["limit"] if 1 <= route["limit"] <= MAX_PORTFOLIO_LIMIT else DEFAULT_PORTFOLIO_LIMIT
    return {"view": view, "limit": limit}, None
