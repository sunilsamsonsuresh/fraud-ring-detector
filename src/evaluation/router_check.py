"""Router test: 40 questions with the expected intent (PLAN-v2.md A10, V15).

The questions live in tests/router_questions.json (5 for each of the 8 intents, some of them
tricky on purpose). Each question goes to the real Question Router (cheap model; answers are cached).
We measure the intent, and the claim ID where the question names one.
"""

import json

from src import config
from src.agents.question_router import question_router

QUESTIONS_FILE = config.PROJECT_ROOT / "tests" / "router_questions.json"


def load_router_questions():
    with open(QUESTIONS_FILE, encoding="utf-8") as file:
        return json.load(file)


def check_router(questions):
    """Return one result per question: expected and chosen intent and claim ID, and if both are right."""
    results = []
    for item in questions:
        route = question_router({"question": item["question"], "current_case": item["current_case"]})["route"]
        chosen_claim_id = route["claim_id"].upper()
        # A question that names no claim may get "" or the chat's current claim: both lead to the same claim.
        claim_id_right = chosen_claim_id == item["claim_id"] or (
            item["claim_id"] == "" and item["current_case"] is not None and chosen_claim_id == item["current_case"])
        results.append({"question": item["question"], "current_case": item["current_case"],
                        "expected_intent": item["intent"], "chosen_intent": route["intent"],
                        "intent_right": route["intent"] == item["intent"],
                        "expected_claim_id": item["claim_id"], "chosen_claim_id": chosen_claim_id,
                        "claim_id_right": claim_id_right})
    return results
