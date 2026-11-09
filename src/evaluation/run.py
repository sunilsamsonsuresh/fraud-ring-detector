"""The evaluate command (PLAN-v2.md V15): layers, agents and router. Results go to data/evaluation/.

- layers: plain code on every claim of the test split (no LLM).
- agents: the workflow (with LLM) on the High and Very High claims and the honest lookalikes of the
          test split, approval turned off.
- router: the 40 questions of tests/router_questions.json (cheap model).
failures.json lists what went wrong: missed fraud claims, false alarms, agent problems, router mistakes.
"""

import json

from src import config
from src.evaluation.agent_runs import run_agents
from src.evaluation.layers import LAYERS, claims_of_split, load_truth, score_layers
from src.evaluation.metrics import layer_metrics
from src.evaluation.report_lines import agent_summary_lines, band_lines, layer_table_lines, recall_lines, router_lines
from src.evaluation.router_check import check_router, load_router_questions
from src.graph.connection import open_neo4j_driver

EVALUATION_DIR = config.DATA_DIR / "evaluation"
HIGH_BANDS = ["High", "Very High"]


def save_json(file_name, value):
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    path = EVALUATION_DIR / file_name
    # default=str writes dates as text; sort_keys keeps the file the same for the same results.
    path.write_text(json.dumps(value, indent=2, default=str, sort_keys=True), encoding="utf-8")
    return path


def read_json(file_name):
    path = EVALUATION_DIR / file_name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_layers():
    """Score the test split in the three layers. Return (rows by layer, printable lines)."""
    truth = load_truth()
    claim_ids = claims_of_split(truth, "test")
    driver = open_neo4j_driver()
    try:
        rows = score_layers(driver, truth, claim_ids)
    finally:
        driver.close()
    metrics = {layer: layer_metrics(rows[layer]) for layer in LAYERS}
    save_json("layers.json", {"rows": rows, "metrics": metrics})
    lines = layer_table_lines(metrics, len(claim_ids)) + [""] + band_lines(metrics) + [""] + recall_lines(metrics)
    return rows, lines


def agent_claims(layer_rows):
    """The High and Very High claims of layer (c), then the honest lookalikes, of the test split."""
    high = [row["claim_id"] for row in layer_rows["c_plus_challenger"] if row["band"] in HIGH_BANDS]
    lookalikes = [row["claim_id"] for row in sorted(layer_rows["c_plus_challenger"],
                                                    key=lambda row: (row["lookalike_group"] or "", row["claim_id"]))
                  if row["lookalike_group"] and not row["is_fraud"] and row["claim_id"] not in high]
    return high + lookalikes


def evaluate_agents(layer_rows, limit=None):
    claim_ids = agent_claims(layer_rows)[:limit] if limit else agent_claims(layer_rows)
    plain_scores = {row["claim_id"]: row["total_score"] for row in layer_rows["c_plus_challenger"]}
    records = run_agents(claim_ids, plain_scores)
    truth = load_truth()
    for record in records:
        claim = truth["claims"][record["claim_id"]]
        record.update({"is_fraud": claim["is_fraud"], "group": claim["group"]})
    save_json("agents_sample.json" if limit else "agents.json", records)
    return records, agent_summary_lines(records)


def evaluate_router():
    results = check_router(load_router_questions())
    save_json("router.json", results)
    return results, router_lines(results)


def failure_list(layer_rows, agent_records, router_results):
    """What went wrong, for the report. Layer (c) is the final score."""
    final_rows = layer_rows["c_plus_challenger"]
    return {
        "fraud_missed_low": [{"claim_id": row["claim_id"], "fraud_type": row["fraud_type"],
                              "total_score": row["total_score"], "fired_rules": row["fired_rules"]}
                             for row in final_rows if row["is_fraud"] and row["band"] == "Low"],
        "honest_flagged_medium_or_above": [{"claim_id": row["claim_id"], "lookalike_group": row["lookalike_group"],
                                            "band": row["band"], "total_score": row["total_score"],
                                            "fired_rules": row["fired_rules"]}
                                           for row in final_rows if not row["is_fraud"] and row["band"] != "Low"],
        "agent_problems": [record for record in agent_records or []
                           if record["error"] or not record["matches_plain_code"] or record["forbidden_words"]
                           or not record["has_closing_sentence"] or any(record["warnings"].values())],
        "router_mistakes": [result for result in router_results or []
                            if not result["intent_right"] or not result["claim_id_right"]],
    }


def write_failures(layer_rows):
    failures = failure_list(layer_rows, read_json("agents.json") or read_json("agents_sample.json"),
                            read_json("router.json"))
    path = save_json("failures.json", failures)
    counts = ", ".join(f"{key} {len(value)}" for key, value in failures.items())
    return [f"Failure list written to {path}: {counts}"]
