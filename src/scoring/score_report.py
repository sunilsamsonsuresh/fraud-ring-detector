"""Printable text for scores (PLAN-v2.md V7): one claim with the proof of each rule, and
the rule check table of score-all. Plain code only, so the text is the same on every run.
"""

from src import config
from src.scoring.rules_catalog import CATEGORY_NAMES, RULES, RULES_BY_ID

MAX_QUOTE_CHARACTERS = 160
WEAK_FINDINGS_SHOWN = 5


def short_quote(quote):
    if len(quote) <= MAX_QUOTE_CHARACTERS:
        return quote
    return quote[:MAX_QUOTE_CHARACTERS] + "..."


def proof_text(proof):
    """One line of proof. Table values first, then each finding with its document, page and quote."""
    parts = []
    for key, value in proof.items():
        if key == "findings":
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value) or "none"
        parts.append(f"{key} {value}")
    for finding in proof.get("findings", []):
        parts.append(f"{finding['value']} ({finding['confidence']}) in {finding['document_id']} page "
                     f"{finding['page_number']} [{finding['finding_id']}]: \"{short_quote(finding['quote'])}\"")
    return "; ".join(parts)


def score_lines(result):
    """The score of one claim, every fired rule with its points and proof, and the rules not evaluated."""
    lines = [f"Claim {result['claim_id']}: total score {result['total_score']} of 100 -> {result['band']}. "
             f"Action: {result['action']}",
             f"Coverage: {result['coverage_pct']}% of the rule points had data. "
             "A low score with low coverage means 'not examined', not 'clean'.",
             "Category scores: " + ", ".join(f"{category} {score}" for category, score in
                                             result["category_scores"].items())
             + "  (weights " + ", ".join(f"{category} {weight}" for category, weight in
                                         config.CATEGORY_WEIGHTS.items()) + ")",
             "Fired rules:"]
    for rule in result["fired_rules"]:
        lines.append(f"  {rule['rule_id']:<5} {rule['name']:<42} {rule['points']:>3} pts "
                     f"(+{rule['points_in_total']} to the total)")
        lines.append(f"        proof: {proof_text(rule['proof'])}")
    if not result["fired_rules"]:
        lines.append("  none")
    lines.append("Not evaluated (input missing; counts as not fired):")
    for rule_id, rule_result in result["rule_results"].items():
        if rule_result["status"] == "not_evaluated":
            lines.append(f"  {rule_id:<5} {RULES_BY_ID[rule_id].name:<42} {rule_result['proof']['missing']}")
    weak = result["weak_findings"]
    lines.append(f"Weak findings (Low confidence; they fire no rule): {len(weak)}")
    for finding in weak[:WEAK_FINDINGS_SHOWN]:
        lines.append(f"  {finding['feature']} = {finding['value']} in {finding['document_id']} "
                     f"page {finding['page_number']}")
    return lines


def percent(part, whole):
    return f"{part / whole:.0%}" if whole else "-"


def rule_check_lines(result_by_claim_id, truth):
    """For each rule: how often it fires on the claims where it was planted, and on the others.
    The ground truth is used here for MEASURING only. The score never reads it."""
    lines = [f"{'Rule':<5} {'Name':<42} {'planted':>7} {'fired':>6} {'share':>6} {'not eval':>8}   "
             f"{'not planted: fired':>18} {'share':>6}",
             "-" * 112]
    for category in CATEGORY_NAMES:
        for rule in RULES:
            if rule.category != category or not rule.enabled:
                continue
            planted = fired_planted = not_evaluated_planted = 0
            others_evaluated = fired_others = 0
            for claim_id, result in result_by_claim_id.items():
                status = result["rule_results"][rule.rule_id]["status"]
                if rule.rule_id in truth["claims"][claim_id]["planted_rules"]:
                    planted += 1
                    fired_planted += status == "fired"
                    not_evaluated_planted += status == "not_evaluated"
                elif status != "not_evaluated":
                    others_evaluated += 1
                    fired_others += status == "fired"
            lines.append(f"{rule.rule_id:<5} {rule.name:<42} {planted:>7} {fired_planted:>6} "
                         f"{percent(fired_planted, planted):>6} {not_evaluated_planted:>8}   "
                         f"{fired_others:>8} of {others_evaluated:<6} {percent(fired_others, others_evaluated):>6}")
    return lines


def band_count_lines(result_by_claim_id, truth):
    """How many fraud and honest claims fall in each band. Only a first look; V10 measures properly."""
    lines = [f"{'Band':<10} {'fraud':>6} {'honest':>7}"]
    for _, band, _ in config.BANDS:
        fraud = honest = 0
        for claim_id, result in result_by_claim_id.items():
            if result["band"] == band:
                if truth["claims"][claim_id]["is_fraud"]:
                    fraud += 1
                else:
                    honest += 1
        lines.append(f"{band:<10} {fraud:>6} {honest:>7}")
    return lines


def score_all_lines(result_by_claim_id, truth):
    """The score-all printout: the rule check table, the band counts and the demo claims."""
    lines = [f"Scored {len(result_by_claim_id)} claims. A snapshot was saved for each.", ""]
    if truth is None:
        return lines + ["No ground_truth.json, so the rule check table is skipped."]
    lines += ["Rule check: how often each rule fires where it was planted, and where it was not.",
              "('not eval' = an input is missing. NL rules come in V8.)"]
    lines += rule_check_lines(result_by_claim_id, truth)
    lines += ["", "Bands (a first look; V10 sets the bands on the tuning split and measures on the test split):"]
    lines += band_count_lines(result_by_claim_id, truth)
    for kind, claim_id in truth["demo_claims"].items():
        lines += ["", f"--- Demo claim ({kind}) ---"] + score_lines(result_by_claim_id[claim_id])
    return lines
