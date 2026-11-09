"""Agent 5: Risk Scoring v2 (PLAN-v2.md A7, V7).

1. Plain code scores the claim with the rule engine (src/scoring/engine.py) and saves a snapshot.
2. The cheap LLM writes a short summary from the fired rules. It never changes the score.
3. Plain code adds the fixed part: each fired rule, its points and its proof.
The Report Writer puts this explanation in the referral brief (V12).
"""

import datetime

from src import config
from src.graph.connection import open_neo4j_driver
from src.llm import ask_llm
from src.scoring.engine import score_claim
from src.scoring.score_report import proof_text, score_lines
from src.wording import find_forbidden_phrases

SYSTEM_PROMPT = ("You explain a fraud risk score to an insurance claims investigator. Use only the rules given. "
                 "Never say that a person is guilty of fraud; use words like 'possible link', 'unusual pattern' "
                 "and 'needs human review'. Plain text, no lists, at most 3 sentences.")
EXPLAIN_PROMPT = """Claim {claim_id} has risk score {score} of 100 (band {band}). Coverage: {coverage}% of the rule
points had data.
Fired rules (ID, name, points, proof):
{rule_lines}

Write at most 3 sentences: which rules drive the score, and what a human reviewer should check first."""
SUMMARY_MAX_TOKENS = 1000     # 500 cut off the summary of a claim with 6 fired rules (found in V15)


def write_summary(result):
    """The LLM's short summary, or a plain sentence if the LLM fails or uses forbidden words."""
    fallback = (f"Claim {result['claim_id']} has a risk score of {result['total_score']} ({result['band']}). "
                "A human reviewer should check the rules below.")
    rule_lines = [f"- {rule['rule_id']} {rule['name']}, {rule['points']} points: {proof_text(rule['proof'])}"
                  for rule in result["fired_rules"]]
    prompt = EXPLAIN_PROMPT.format(claim_id=result["claim_id"], score=result["total_score"], band=result["band"],
                                   coverage=result["coverage_pct"], rule_lines="\n".join(rule_lines) or "- none")
    try:
        summary = ask_llm(prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, max_tokens=SUMMARY_MAX_TOKENS)
    except RuntimeError as problem:
        return fallback, [f"The LLM call failed, so a plain summary is used: {problem}"]
    if find_forbidden_phrases(summary):
        return fallback, [f"The LLM summary used forbidden words {find_forbidden_phrases(summary)}; not used."]
    return summary, []


def risk_scoring(state):
    driver = open_neo4j_driver()
    try:
        result = score_claim(driver, state["claim_id"], datetime.date.today())
    finally:
        driver.close()
    if result is None:
        return {"error_message": f"Claim {state['claim_id']} was not found in the graph."}
    summary, warnings = write_summary(result)
    explanation = summary + "\n\nRules and proof (plain code):\n" + "\n".join(score_lines(result))
    return {"score_result": result, "risk_score": result["total_score"], "risk_level": result["band"],
            "risk_summary": summary, "risk_explanation": explanation, "risk_warnings": warnings}
