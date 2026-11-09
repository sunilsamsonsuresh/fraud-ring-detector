"""Human approval: the run pauses and waits for the investigator (PLAN-v2.md V13).

The node calls LangGraph's interrupt(). The run stops there, and the state is kept by the
checkpointer (src/workflow.py). The caller shows the brief, gets the answer, and resumes the run
with that answer. Then this node checks the answer and saves the decision.

The three answers:
- approve: the referral goes ahead. The run ends.
- reject:  the referral does not go ahead. The run ends.
- more:    the investigator wants more investigation. One more round runs, then the run
           pauses again. This is allowed MAX_HUMAN_REQUESTS times; after that only
           approve and reject are allowed.
Every decision is one line in data/decisions.jsonl. No LLM is used here.
"""

import datetime
import json

from langgraph.types import interrupt

from src import config

DECISION_CHOICES = ["approve", "reject", "more"]
MAX_REASON_CHARACTERS = 500


def allowed_decisions(state):
    if state.get("human_request_count", 0) < config.MAX_HUMAN_REQUESTS:
        return list(DECISION_CHOICES)
    return ["approve", "reject"]


def check_answer(answer, allowed):
    """Return (decision, reason, problem). problem is None when the answer is good."""
    if not isinstance(answer, dict):
        return None, "", "The answer is not a dict."
    decision = str(answer.get("decision", "")).strip().lower()
    reason = " ".join(str(answer.get("reason", "")).split())[:MAX_REASON_CHARACTERS]
    if decision not in allowed:
        return None, reason, f"The decision '{decision}' is not allowed. Allowed: {', '.join(allowed)}."
    if decision in ["reject", "more"] and not reason:
        return None, reason, f"The decision '{decision}' needs a reason."
    return decision, reason, None


def save_decision(record):
    """Add one line to data/decisions.jsonl. Older lines are never changed."""
    config.DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.DECISIONS_FILE, "a", encoding="utf-8") as decisions_file:
        decisions_file.write(json.dumps(record, sort_keys=True) + "\n")


def human_approval(state):
    allowed = allowed_decisions(state)
    # The run stops here. On resume, LangGraph runs this node again from the top, and
    # interrupt() returns the investigator's answer instead of stopping.
    answer = interrupt({"claim_id": state["claim_id"], "band": state["final_risk_level"],
                        "total_score": state["final_risk_score"], "report_text": state["report_text"],
                        "allowed_decisions": allowed})
    decision, reason, problem = check_answer(answer, allowed)
    if problem is not None:
        return {"error_message": f"No decision was saved. {problem}"}
    record = {"claim_id": state["claim_id"], "band": state["final_risk_level"],
              "total_score": state["final_risk_score"], "decision": decision, "reason": reason,
              "decided_on": datetime.date.today().isoformat(), "round": state.get("loop_count", 0) + 1}
    save_decision(record)
    update = {"human_decision": decision, "human_reason": reason, "decision_record": record}
    if decision == "more":
        update["human_request_count"] = state.get("human_request_count", 0) + 1
        update["investigator_request"] = reason      # the Graph Investigator's question for the next round
    return update


def ask_investigator_in_terminal(pause_value):
    """Show the brief and ask for a decision in the terminal. Ask again until the answer is valid."""
    print()
    print(pause_value["report_text"])
    allowed = pause_value["allowed_decisions"]
    while True:
        decision = input(f"Decision for {pause_value['claim_id']} ({' / '.join(allowed)}): ").strip().lower()
        reason = input("Reason (needed for reject and more): ").strip()
        decision, reason, problem = check_answer({"decision": decision, "reason": reason}, allowed)
        if problem is None:
            return {"decision": decision, "reason": reason}
        print(problem)
