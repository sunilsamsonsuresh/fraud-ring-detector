"""The referral brief: the fixed parts, built by plain code from the state (PLAN-v2.md V12).

build_brief makes a plain dict (saved as JSON in data/reports/, so a later web page can read it).
brief_markdown turns it into text for the terminal. Facts and sources never come from the LLM;
the Report Writer only adds a short narrative (brief["narrative"]).
"""

from src import config
from src.scoring.history import changed_snapshots, peak_index, trend_of
from src.scoring.rules_catalog import RULES_BY_ID
from src.scoring.score_report import proof_text

CLOSING_SENTENCE = "Possible link, needs human review. This brief is not a finding of fraud."
MAX_LINKED_CLAIMS = 15
MAX_VIA_LINKS = 2


def fired_rule_rows(final, rule_quotes):
    rows = []
    for rule in final["fired_rules"]:
        sources = sorted({f"{item['document_id']}, page {item['page_number']}"
                          for item in rule["proof"].get("findings", [])})
        quotes = [quote for quote in rule_quotes if quote["rule_id"] == rule["rule_id"]]
        rows.append({"rule_id": rule["rule_id"], "name": rule["name"], "points": rule["points"],
                     "points_in_total": rule["points_in_total"], "proof": proof_text(rule["proof"]),
                     "sources": sources, "quotes": quotes})
    return rows


def has_network_rule_link(entry):
    """True when a network-rule template (nl_...) found the link; round 2 templates find weaker links."""
    return any(link["template"].startswith("nl_") for link in entry["links"])


def link_text(link, claim_id):
    """One reason for a link. A link found through another claim names that claim ("via")."""
    text = f"{link['template']} = {link['shared_value']}"
    if link["via_claim_id"] != claim_id:
        text += f" (via {link['via_claim_id']})"
    return text


def network_rows(linked_claims, claim_id):
    """The linked claims, those found by the network-rule templates first, then by hop and claim ID."""
    ordered = sorted(linked_claims, key=lambda entry: (not has_network_rule_link(entry), entry["hop"],
                                                       entry["claim_id"]))
    rows = []
    for entry in ordered[:MAX_LINKED_CLAIMS]:
        # Direct links explain the claim best. A claim reached only through others shows 2 of those paths.
        direct = sorted({link_text(link, claim_id) for link in entry["links"] if link["via_claim_id"] == claim_id})
        why = direct or sorted({link_text(link, claim_id) for link in entry["links"]})[:MAX_VIA_LINKS]
        rows.append({"claim_id": entry["claim_id"], "hop": entry["hop"], "why": why})
    return rows


def missing_rows(final):
    rows = []
    for rule_id, result in final["rule_results"].items():
        if result["status"] == "not_evaluated":
            rows.append(f"{rule_id} {RULES_BY_ID[rule_id].name}: {result['proof']['missing']}")
    if final["weak_findings"]:
        rows.append(f"{len(final['weak_findings'])} weak findings (Low confidence) fire no rule.")
    if final["coverage_pct"] < config.LOW_COVERAGE_PCT:
        rows.append(f"Coverage {final['coverage_pct']}%: not fully examined.")
    return rows


def history_summary(history):
    if not history:
        return None
    peak = history[peak_index(history)]
    rows = []
    for row in changed_snapshots(history):
        rows.append({"as_of_date": row["as_of_date"].isoformat(), "total_score": row["total_score"],
                     "band": row["band"], "changes": row["changes"], "is_peak": row["is_peak"]})
    return {"peak_score": peak["result"]["total_score"], "peak_date": peak["as_of_date"].isoformat(),
            "trend": trend_of(history), "rows": rows}


def build_brief(state, history):
    final = state["final_score_result"]
    review = state.get("litigation_review")
    return {
        "claim_id": state["claim_id"], "band": final["band"], "action": final["action"],
        "total_score": final["total_score"], "score_before_challenger": state["score_result"]["total_score"],
        "band_before_challenger": state["score_result"]["band"], "rounds": state.get("loop_count", 0) + 1,
        "category_scores": final["category_scores"], "coverage_pct": final["coverage_pct"],
        "fired_rules": fired_rule_rows(final, state.get("rule_quotes", [])),
        "network": network_rows(state.get("linked_claims", []), state["claim_id"]),
        "linked_claim_count": len(state.get("linked_claims", [])),
        "challenger_notes": [{"check": item["check"], "rules": item["rules"], "detail": item["detail"],
                              "effect": item["effect"], "explanation": item.get("explanation", "")}
                             for item in state.get("challenges", [])],
        "other_innocent_explanations": state.get("challenger_review", {}).get("other_innocent_explanations", []),
        "missing": missing_rows(final),
        "history": history_summary(history),
        "litigation": review,
        "score_explanation": state.get("risk_summary", ""),
        "narrative": "",
        "closing": CLOSING_SENTENCE,
        "warnings": [],
    }


def brief_markdown(brief):
    scores = ", ".join(f"{category} {score}" for category, score in brief["category_scores"].items())
    parts = [f"# Referral brief: claim {brief['claim_id']}",
             f"**Band: {brief['band']}** ({brief['total_score']} of 100). Action: {brief['action']}  ",
             f"Before the Challenger: {brief['score_before_challenger']} ({brief['band_before_challenger']}). "
             f"Rounds: {brief['rounds']}.",
             f"Category scores: {scores}. Coverage: {brief['coverage_pct']}%.",
             brief["narrative"].strip() or "(no narrative)",
             "## Score explanation\n" + (brief["score_explanation"] or "-")]
    rules = []
    for rule in brief["fired_rules"]:
        rules.append(f"- **{rule['rule_id']} {rule['name']}** ({rule['points']} pts, +{rule['points_in_total']}): "
                     f"{rule['proof']}")
    parts.append("## Fired rules with proof\n" + ("\n".join(rules) or "- none"))
    network = [f"- {row['claim_id']} (hop {row['hop']}): {'; '.join(row['why'])}" for row in brief["network"]]
    if brief["linked_claim_count"] > len(brief["network"]):
        network.append(f"- ... and {brief['linked_claim_count'] - len(brief['network'])} more linked claims")
    parts.append("## Network picture\n" + ("\n".join(network) or "- no linked claims"))
    notes = []
    for note in brief["challenger_notes"]:
        changed = f" Rules changed: {', '.join(note['rules'])}." if note["rules"] else ""
        notes.append(f"- **{note['check']}**: {note['effect']}{changed} {note['explanation']}".rstrip())
    for item in brief["other_innocent_explanations"]:
        notes.append(f"- {item['rule_id']} (note, no points changed): {item['explanation']} Based on: {item['based_on']}")
    parts.append("## Challenger notes\n" + ("\n".join(notes) or "- none"))
    if brief["litigation"]:
        review = brief["litigation"]
        lines = [f"{review['assessment']}: {review['reason']} {review.get('summary', '')}".strip()]
        lines += [f"- {point['finding']} (source: {point['source']})" for point in review["points"]]
        parts.append("## Litigation\n" + "\n".join(lines))
    parts.append("## What is missing\n" + ("\n".join(f"- {row}" for row in brief["missing"]) or "- nothing"))
    history = brief["history"]
    if history:
        rows = [f"- {row['as_of_date']}: {row['total_score']} ({row['band']}) {' '.join(row['changes'])}"
                + (" <- peak" if row["is_peak"] else "") for row in history["rows"]]
        parts.append(f"## Score history (peak {history['peak_score']} on {history['peak_date']}, "
                     f"trend {history['trend']})\n" + "\n".join(rows))
    if brief["warnings"]:
        parts.append("## Warnings\n" + "\n".join(f"- {warning}" for warning in brief["warnings"]))
    parts.append(f"**{brief['closing']}**")
    return "\n\n".join(parts) + "\n"
