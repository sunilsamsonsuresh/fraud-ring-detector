"""One fixed path for each intent (PLAN-v2.md A9, V14). Plain code only; the LLM is not called here,
except by the full investigation (investigate_claim), which is the normal workflow.

Each tool gets checked parameters (src/questions/checks.py) and returns a tool result:
  {"facts": ..., "notes": [...], "sources": [...]}   or   {"message": "..."} when there is nothing to show.
The Answer Writer may only use these facts. The sources come from here, never from the LLM.
"""

import datetime
import json

from src.agents.graph_investigator import network_links
from src.graph import queries
from src.graph.network import read_network_facts, rows_of
from src.graph.retrieval import search_text_in_claims
from src.questions.portfolio import portfolio_overview
from src.scoring.challenge_checks import read_rule_fire_shares
from src.scoring.facts import read_raw_facts
from src.scoring.history import changed_snapshots, peak_index, score_history, trend_of
from src.scoring.rules_catalog import CATEGORY_NAMES, RULES_BY_ID, SOURCE_NAMES
from src.scoring.score_report import proof_text

SEARCH_RESULTS = 5
SNIPPET_CHARACTERS = 400
MAX_LINKED_CLAIMS = 25


def finding_sources(fired_rules):
    sources = set()
    for rule in fired_rules:
        for finding in rule["proof"].get("findings", []):
            sources.add(f"{finding['document_id']}, page {finding['page_number']}")
    return sorted(sources)


def explain_score(driver, claim_id):
    records, _, _ = driver.execute_query(queries.LATEST_SNAPSHOT_OF_CLAIM, claim_id=claim_id)
    if not records:
        return {"message": f"Claim {claim_id} has no saved score yet. Run: python main.py score-claim {claim_id}"}
    row = rows_of(records)[0]
    fired_rules = json.loads(row["fired_rules_json"])
    rules = [{"rule_id": rule["rule_id"], "name": rule["name"], "points": rule["points"],
              "adds_to_total": rule["points_in_total"], "proof": proof_text(rule["proof"])} for rule in fired_rules]
    facts = {"claim_id": claim_id, "total_score": row["total_score"], "band": row["band"],
             "coverage_pct": row["coverage_pct"], "scored_on": row["as_of_date"].isoformat(), "fired_rules": rules,
             "band_after_challenger": row["investigated_band"], "score_after_challenger": row["investigated_score"],
             "investigation_summary": row["investigated_summary"]}
    notes = ["The score comes from fixed rules in plain code. The LLM did not set it."]
    if row["investigated_band"] is None:
        notes.append(f"The Challenger has not checked this claim yet (python main.py investigate {claim_id}).")
    return {"facts": facts, "notes": notes,
            "sources": [f"ScoreSnapshot {row['snapshot_id']}"] + finding_sources(fired_rules)}


def score_history_of(driver, claim_id):
    """Scored again on each event date, with only the facts known on that date. Nothing is saved."""
    raw = read_raw_facts(driver, claim_id)
    history = score_history(raw)
    if not history:
        return {"message": f"Claim {claim_id} has no event dates to score."}
    rows = []
    for row in changed_snapshots(history):
        rows.append({"as_of_date": row["as_of_date"].isoformat(), "total_score": row["total_score"],
                     "band": row["band"], "rules_changed": row["changes"], "is_peak": row["is_peak"]})
    peak = history[peak_index(history)]
    facts = {"claim_id": claim_id, "changes": rows, "peak_score": peak["result"]["total_score"],
             "peak_date": peak["as_of_date"].isoformat(), "trend": trend_of(history)}
    return {"facts": facts, "notes": ["+BI-2 means rule BI-2 started to fire on that date; -AS-1 means it stopped."],
            "sources": [f"facts of {claim_id} in the graph, scored as of each event date (no look-ahead)"]}


def search_documents(driver, claim_id, topic):
    results = search_text_in_claims(driver, topic, [claim_id], limit=SEARCH_RESULTS)
    if not results:
        return {"message": f"Claim {claim_id} has no searchable text. Run: python main.py ingest-documents --chunks"}
    snippets = []
    for result in results:
        snippets.append({"source": f"{result['file_name']}, page {result['page_number']}",
                         "similarity": round(result["score"], 3), "text": result["text"][:SNIPPET_CHARACTERS]})
    return {"facts": {"claim_id": claim_id, "topic": topic, "snippets": snippets},
            "notes": ["The snippets are the closest text in meaning. They may not answer the question."],
            "sources": [snippet["source"] for snippet in snippets]}


def connections_of_claim(driver, claim_id):
    links = network_links(read_network_facts(driver, claim_id), claim_id)
    reasons_by_claim = {}
    for link in links:
        if link["source_claim_id"] == claim_id:          # direct links only; the cluster is in the brief
            reasons_by_claim.setdefault(link["linked_claim_id"], set()).add(
                f"{link['template']} = {link['shared_value']}")
    facts = [{"claim_id": other, "why": sorted(reasons)} for other, reasons in sorted(reasons_by_claim.items())]
    notes = ["Links inside the same incident are not counted."]
    if len(facts) > MAX_LINKED_CLAIMS:
        notes.append(f"{len(facts)} linked claims; the first {MAX_LINKED_CLAIMS} are shown.")
    return {"facts": {"claim_id": claim_id, "linked_claims": facts[:MAX_LINKED_CLAIMS]}, "notes": notes,
            "sources": [f"network templates (src/graph/queries.py, Part 10) for {claim_id}"]}


def claims_with_phone(driver, phone_end):
    records, _, _ = driver.execute_query(queries.CLAIMS_WITH_PHONE, phone_end=phone_end)
    rows = rows_of(records)
    if not rows:
        return {"message": f"No claim has a phone number ending in {phone_end}."}
    return {"facts": {"phone": phone_end, "claims": rows}, "notes": [],
            "sources": [f"Phone nodes ending in {phone_end}"]}


def claims_linked_to_name(driver, name):
    records, _, _ = driver.execute_query(queries.CLAIMS_LINKED_TO_NAME, name=name, exact=True)
    if not records:
        records, _, _ = driver.execute_query(queries.CLAIMS_LINKED_TO_NAME, name=name, exact=False)
    rows = rows_of(records)
    names = sorted({row["shared_value"] for row in rows})
    if not rows:
        return {"message": f"No clinic, repair shop, attorney or law firm named '{name}' was found."}
    if len(names) > 1:
        return {"message": f"Several names contain '{name}': {', '.join(names[:10])}. Which one do you mean?"}
    claim_ids = sorted({row["claim_id"] for row in rows})
    return {"facts": {"name": names[0], "link_types": sorted({row["link_type"] for row in rows}),
                      "claim_count": len(claim_ids), "claim_ids": claim_ids},
            "notes": ["Sharing a busy provider alone is not network evidence (Challenger, busy provider check)."],
            "sources": [f"graph links to '{names[0]}'"]}


def rule_lookup(driver, rule_id):
    rule = RULES_BY_ID[rule_id]
    shares = read_rule_fire_shares(driver)
    facts = {"rule_id": rule_id, "name": rule.name, "category": CATEGORY_NAMES[rule.category],
             "points": rule.points, "fires_when": rule.description, "input": SOURCE_NAMES[rule.source],
             "enabled": rule.enabled,
             "share_of_claims_firing": f"{shares[rule_id]:.0%}" if rule_id in shares else "no saved scores"}
    return {"facts": facts, "notes": [], "sources": ["src/scoring/rules_catalog.py", "latest ScoreSnapshots"]}


def investigate(claim_id):
    # Imported here: the workflow module imports many agents, and only this tool needs it.
    from src.workflow import investigate_claim
    state = investigate_claim(claim_id)          # no approval step in questions; use `investigate` to decide
    if state.get("error_message"):
        return {"message": state["error_message"]}
    brief = state["report_brief"]
    facts = {"claim_id": claim_id, "band": brief["band"], "total_score": brief["total_score"],
             "score_before_challenger": brief["score_before_challenger"], "action": brief["action"],
             "fired_rules": [f"{rule['rule_id']} {rule['name']}" for rule in brief["fired_rules"]],
             "linked_claim_count": brief["linked_claim_count"], "summary": state["saved_summary"],
             "investigated_on": datetime.date.today().isoformat()}
    return {"facts": facts, "notes": [],
            "sources": [state["report_file"]] + finding_sources(state["final_score_result"]["fired_rules"])}


def run_tool(driver, intent, parameters):
    """The fixed path of the intent. The parameters were checked by plain code."""
    if intent == "investigate_claim":
        return investigate(parameters["claim_id"])
    if intent == "explain_score":
        return explain_score(driver, parameters["claim_id"])
    if intent == "score_history":
        return score_history_of(driver, parameters["claim_id"])
    if intent == "search_documents":
        return search_documents(driver, parameters["claim_id"], parameters["topic"])
    if intent == "rule_lookup":
        return rule_lookup(driver, parameters["rule_id"])
    if intent == "portfolio_overview":
        return portfolio_overview(driver, parameters["view"], parameters["limit"])
    # explore_connections
    if "phone_end" in parameters:
        return claims_with_phone(driver, parameters["phone_end"])
    if "name" in parameters:
        return claims_linked_to_name(driver, parameters["name"])
    return connections_of_claim(driver, parameters["claim_id"])
