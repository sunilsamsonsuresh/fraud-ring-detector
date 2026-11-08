"""Agent 5: Risk Scoring (PLAN.md, Step 8 and A8).

1. Plain code collects the signals. Each signal has a list of evidence items, and
   each item names its source (a graph link, a document page, a lawsuit record).
2. Plain code turns each signal into points with the weights in config.py and adds them.
   Same input -> same score. The graph signals come from the six fixed templates, run
   here by plain code, so the score does not depend on which templates the LLM chose.
3. The cheap LLM writes a short summary. It never changes the score.
"""

from src import config
from src.graph.connection import open_neo4j_driver
from src.graph.investigation import run_link_template
from src.llm import ask_llm
from src.wording import find_forbidden_phrases

# signal name -> the template whose hop-1 links count for it
SINGLE_LINK_SIGNALS = {
    "shared_phone": "claims_sharing_phone",
    "shared_address": "claims_sharing_address",
    "shared_repair_shop": "claims_sharing_repair_shop",
    "shared_clinic": "claims_sharing_clinic",
}
# signal name -> the two templates that must BOTH link the same other claim
DOUBLE_LINK_SIGNALS = {
    "law_firm_and_clinic_together": ("claims_sharing_law_firm", "claims_sharing_clinic"),
    "law_firm_and_expert_together": ("claims_sharing_law_firm", "claims_sharing_expert"),
}
SOURCES_SHOWN_PER_SIGNAL = 5
ALL_TEMPLATES = ["claims_sharing_phone", "claims_sharing_address", "claims_sharing_repair_shop",
                 "claims_sharing_clinic", "claims_sharing_law_firm", "claims_sharing_expert"]

SYSTEM_PROMPT = ("You explain a fraud risk score to an insurance claims investigator. Use only the signals given. "
                 "Never say that a person is guilty of fraud; use words like 'possible link', 'unusual pattern' "
                 "and 'needs human review'. Plain text, no lists, at most 3 sentences.")
EXPLAIN_PROMPT = """Claim {claim_id} has risk score {score} of {max_score} ({level}).
Signals (points, evidence count, description):
{signal_lines}

Write at most 3 sentences: which signals drive the score, and what a human reviewer should check first."""


def make_signal(name, description, evidence):
    points_per_item, max_points = config.RISK_SIGNAL_WEIGHTS[name]
    return {"name": name, "description": description, "count": len(evidence),
            "points": min(len(evidence) * points_per_item, max_points), "max_points": max_points,
            "evidence": evidence}


def read_graph_links(driver, claim_id):
    """{other claim ID: {template name: shared value}} for every hop-1 link of the six templates."""
    links_by_claim = {}
    for template in ALL_TEMPLATES:
        for link in run_link_template(driver, template, [claim_id]):
            links_by_claim.setdefault(link["linked_claim_id"], {})[template] = link["shared_value"]
    return links_by_claim


def graph_signals(links_by_claim):
    signals = []
    for name, template in SINGLE_LINK_SIGNALS.items():
        evidence = []
        for other_claim_id in sorted(links_by_claim):
            templates = links_by_claim[other_claim_id]
            if template in templates:
                evidence.append({"claim_id": other_claim_id,
                                 "source": f"graph ({template}): {templates[template]}"})
        signals.append(make_signal(name, f"Other claims linked by {template}", evidence))
    for name, (first, second) in DOUBLE_LINK_SIGNALS.items():
        evidence = []
        for other_claim_id in sorted(links_by_claim):
            templates = links_by_claim[other_claim_id]
            if first in templates and second in templates:
                evidence.append({"claim_id": other_claim_id,
                                 "source": f"graph: {templates[first]} + {templates[second]}"})
        signals.append(make_signal(name, f"Other claims linked by both {first} and {second}", evidence))
    return signals


def document_signals(state):
    # copied_text has one row per chunk pair; count each other claim once, with its best pair.
    best_copy_by_claim = {}
    for copy in state.get("copied_text", []):
        best = best_copy_by_claim.get(copy["other_claim_id"])
        if best is None or copy["score"] > best["score"]:
            best_copy_by_claim[copy["other_claim_id"]] = copy
    copy_evidence = []
    for other_claim_id in sorted(best_copy_by_claim):
        copy = best_copy_by_claim[other_claim_id]
        copy_evidence.append({"claim_id": other_claim_id,
                              "source": f"{copy['document_id']} page {copy['page_number']} ~ "
                                        f"{copy['other_document_id']} page {copy['other_page_number']} "
                                        f"(similarity {copy['score']})"})
    conflict_evidence = []
    for conflict in state.get("document_conflicts", []):
        conflict_evidence.append({"source": f"{conflict['document_id']} page {conflict['page_number']}: "
                                            f"{conflict['field']} table {conflict['table_value']} vs "
                                            f"document {conflict['document_value']}"})
    return [make_signal("copied_text", "Other claims with near-copies of this claim's text", copy_evidence),
            make_signal("document_conflicts", "Values in the PDFs that differ from the tables", conflict_evidence)]


def describe_lawsuit(lawsuit):
    return (f"lawsuit {lawsuit['lawsuit_id']} (claim {lawsuit['claim_id']}): filed {lawsuit['filed_date']}, "
            f"{lawsuit['days_before_deadline']} days before the deadline, demand {lawsuit['demand_amount']:.0f}")


def litigation_signals(state):
    facts = state.get("litigation_facts") or {}
    own_evidence = []
    if facts.get("filed_near_deadline"):
        own_evidence.append({"claim_id": state["claim_id"], "source": describe_lawsuit(facts["own_lawsuit"])})
    near_evidence = []
    for lawsuit in facts.get("related_near_deadline", []):
        near_evidence.append({"claim_id": lawsuit["claim_id"], "source": describe_lawsuit(lawsuit)})
    demand_evidence = []
    for lawsuit in facts.get("similar_demands", []):
        demand_evidence.append({"claim_id": lawsuit["claim_id"], "source": describe_lawsuit(lawsuit)})
    return [
        make_signal("lawsuit_filed_near_deadline",
                    f"This claim's lawsuit was filed {config.NEAR_DEADLINE_DAYS} days or less before the deadline",
                    own_evidence),
        make_signal("related_lawsuits_near_deadline",
                    "Lawsuits with the same plaintiff firm or expert, filed near the deadline", near_evidence),
        make_signal("similar_demand_amounts",
                    f"Lawsuits with the same plaintiff firm or expert and a demand within "
                    f"{config.SIMILAR_DEMAND_SHARE:.0%}", demand_evidence),
    ]


def total_score(signals, discounted_signal_names=()):
    """Add up the points. A discounted signal keeps only part of its points (Challenger, Step 9)."""
    total = 0
    for signal in signals:
        points = signal["points"]
        if signal["name"] in discounted_signal_names:
            points = int(points * config.CHALLENGER_DISCOUNT)   # int() drops the decimals: 15 * 0.5 -> 7
        total += points
    return min(total, config.MAX_RISK_SCORE)


def risk_level(score):
    if score >= config.HIGH_RISK_MIN_SCORE:
        return "high"
    if score >= config.MEDIUM_RISK_MIN_SCORE:
        return "medium"
    return "low"


def signal_lines(signals):
    """One line per signal with points, then its evidence sources. The fixed, repeatable part.
    The full evidence list stays in state["risk_signals"]; the text shows the first few."""
    lines = []
    for signal in signals:
        if signal["count"] == 0:
            continue
        lines.append(f"- {signal['name']}: {signal['points']}/{signal['max_points']} points, "
                     f"{signal['count']} evidence items. {signal['description']}.")
        for item in signal["evidence"][:SOURCES_SHOWN_PER_SIGNAL]:
            claim_part = f"{item['claim_id']}: " if "claim_id" in item else ""
            lines.append(f"    source: {claim_part}{item['source']}")
        if signal["count"] > SOURCES_SHOWN_PER_SIGNAL:
            lines.append(f"    ... and {signal['count'] - SOURCES_SHOWN_PER_SIGNAL} more")
    return lines


def collect_signals(state):
    driver = open_neo4j_driver()
    try:
        links_by_claim = read_graph_links(driver, state["claim_id"])
    finally:
        driver.close()
    return graph_signals(links_by_claim) + document_signals(state) + litigation_signals(state)


def write_summary(claim_id, score, level, signals):
    """The LLM's short summary, or a plain sentence if the LLM fails or uses forbidden words."""
    summary_lines = [line for line in signal_lines(signals) if not line.startswith("    ")]
    fallback = f"Claim {claim_id} has a {level} risk score of {score}. A human reviewer should check the signals below."
    prompt = EXPLAIN_PROMPT.format(claim_id=claim_id, score=score, max_score=config.MAX_RISK_SCORE, level=level,
                                   signal_lines="\n".join(summary_lines) or "- no signals")
    try:
        summary = ask_llm(prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, max_tokens=500)
    except RuntimeError as problem:
        return fallback, [f"The LLM call failed, so a plain summary is used: {problem}"]
    if find_forbidden_phrases(summary):
        return fallback, [f"The LLM summary used forbidden words {find_forbidden_phrases(summary)}; not used."]
    return summary, []


def risk_scoring(state):
    signals = collect_signals(state)
    score = total_score(signals)
    level = risk_level(score)
    summary, warnings = write_summary(state["claim_id"], score, level, signals)
    explanation = summary + "\n\nSignals and sources:\n" + ("\n".join(signal_lines(signals)) or "- none")
    return {"risk_signals": signals, "risk_score": score, "risk_level": level,
            "risk_explanation": explanation, "risk_warnings": warnings}
