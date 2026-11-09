"""Run the agent workflow on chosen claims and measure the agents (PLAN-v2.md V15).

The workflow runs with approval turned off (no pause). For each claim plain code records:
- did the run finish, how many rounds, did the Litigation Analyst run,
- does the final score equal the plain-code layer (c) score (the LLM must not change points),
- the warnings of each agent (an LLM fallback is a warning),
- forbidden words in the brief (CLAUDE.md, rule 14) and the closing sentence,
- how many Challenger checks got an explanation from the LLM,
- seconds and the new LLM calls with their cost (from the new cache files).
The workflow saves what it always saves: a snapshot, the Claim node fields and data/reports/<claim>.json.
"""

import json
import time

from src import config
from src.reports.referral_brief import CLOSING_SENTENCE
from src.wording import find_forbidden_phrases
from src.workflow import investigate_claim

WARNING_KEYS = ["intake_warnings", "graph_warnings", "litigation_warnings", "risk_warnings", "challenger_warnings",
                "report_warnings"]


def cache_file_names():
    return {path.name for path in config.CACHE_DIR.glob("*.json")}


def cost_of_new_calls(names_before):
    """(number of new LLM calls, cost in dollars, calls by model) since names_before."""
    calls, cost, calls_by_model = 0, 0.0, {}
    for name in sorted(cache_file_names() - names_before):
        with open(config.CACHE_DIR / name, encoding="utf-8") as file:
            entry = json.load(file)
        input_price, output_price = config.MODEL_PRICES_PER_MILLION[entry["model"]]
        cost += (entry["input_tokens"] * input_price + entry["output_tokens"] * output_price) / 1_000_000
        calls += 1
        calls_by_model[entry["model"]] = calls_by_model.get(entry["model"], 0) + 1
    return calls, cost, calls_by_model


def run_one_claim(claim_id, plain_score):
    names_before = cache_file_names()
    started = time.monotonic()
    state = investigate_claim(claim_id)                 # no get_human_answer: approval is off
    seconds = round(time.monotonic() - started, 1)
    calls, cost, _ = cost_of_new_calls(names_before)
    record = {"claim_id": claim_id, "seconds": seconds, "new_llm_calls": calls, "cost": round(cost, 4)}
    if state.get("error_message"):
        record["error"] = state["error_message"]
        return record
    challenges = state.get("challenges", [])
    record.update({
        "error": None,
        "rounds": state.get("loop_count", 0) + 1,
        "litigation_ran": "litigation_facts" in state,       # only the Litigation Analyst sets this field
        "score_before_challenger": state["score_result"]["total_score"],
        "final_score": state["final_risk_score"], "final_band": state["final_risk_level"],
        "plain_code_score": plain_score, "matches_plain_code": state["final_risk_score"] == plain_score,
        "warnings": {key: len(state.get(key, [])) for key in WARNING_KEYS},
        "forbidden_words": find_forbidden_phrases(state["report_text"]),
        "has_closing_sentence": CLOSING_SENTENCE in state["report_text"],
        "challenges": len(challenges),
        "challenges_explained": sum(1 for item in challenges if item.get("explanation")),
        "asked_for_more_evidence": state["challenger_review"].get("needs_more_evidence", False)
                                   or state.get("loop_count", 0) > 0,
        "other_innocent_explanations": len(state["challenger_review"].get("other_innocent_explanations", [])),
    })
    return record


def run_agents(claim_ids, plain_score_by_claim):
    records = []
    for number, claim_id in enumerate(claim_ids, start=1):
        record = run_one_claim(claim_id, plain_score_by_claim[claim_id])
        records.append(record)
        status = record["error"] or f"{record['final_band']} {record['final_score']}"
        print(f"  [{number}/{len(claim_ids)}] {claim_id}: {status} ({record['seconds']} s, "
              f"{record['new_llm_calls']} new calls, ${record['cost']})")
    return records
