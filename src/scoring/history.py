"""The score of one claim over time, with no look-ahead (PLAN-v2.md V9).

1. Event dates: every date on which a fact of the claim became known (a visit, a payment,
   a reserve change, a lawsuit, a finding, another linked claim reported ...). See as_of.py.
2. For each event date, score the claim with only the facts known on that date.
3. The peak is the first snapshot with the highest score.
4. The trend compares the latest score with the score TREND_DAYS earlier:
   up by TREND_MIN_CHANGE or more = "rising", down by that much = "declining", else "stable".
"""

import datetime

from src import config
from src.graph import queries
from src.scoring.as_of import facts_as_of, known_from
from src.scoring.engine import save_snapshot, score_facts


def event_dates(raw):
    """The sorted dates on which something about the claim became known (from the reported date on)."""
    dates = [raw["reported_date"], raw["attorney_retained_date"]]
    dates += raw["visit_dates"]
    dates += [payment["payment_date"] for payment in raw["payments"]]
    dates += [event["event_date"] for event in raw["reserve_events"]]
    dates += [lawsuit["filed_date"] for lawsuit in raw["lawsuits"]]
    dates += [known_from(finding["document_type"], raw, finding["note_date"]) for finding in raw["all_findings"]]
    dates += [known_from(document["document_type"], raw) for document in raw["document_loss_dates"]]
    dates += list((raw["incident_claimants"] or {}).values())
    network = raw["network"]
    dates += list(network["reported_dates"].values())
    dates += [other["reported_date"] for other in network["repeat_claims"]]
    dates += [copy["other_reported_date"] for copy in network["copied_story"]]
    dates += [link["linked_filed_date"] for link in network["cluster_links"]]
    kept = set()
    for date in dates:
        if date is not None:
            kept.add(max(date, raw["reported_date"]))     # nothing is known before the report
    return sorted(kept)


def score_history(raw):
    """[{"as_of_date", "result"}] for each event date, oldest first."""
    history = []
    for as_of_date in event_dates(raw):
        result = score_facts(facts_as_of(raw, as_of_date))
        history.append({"as_of_date": as_of_date, "result": result})
    return history


def peak_index(history):
    best = 0
    for index, snapshot in enumerate(history):
        if snapshot["result"]["total_score"] > history[best]["result"]["total_score"]:
            best = index
    return best


def trend_of(history):
    """"rising", "stable" or "declining" (see the top of this file)."""
    latest = history[-1]
    compare_date = latest["as_of_date"] - datetime.timedelta(days=config.TREND_DAYS)
    earlier = history[0]
    for snapshot in history:
        if snapshot["as_of_date"] <= compare_date:
            earlier = snapshot
    change = latest["result"]["total_score"] - earlier["result"]["total_score"]
    if change >= config.TREND_MIN_CHANGE:
        return "rising"
    if change <= -config.TREND_MIN_CHANGE:
        return "declining"
    return "stable"


def save_history(driver, claim_id, history):
    """One snapshot per event date, and the peak flag on the snapshots of the claim."""
    for snapshot in history:
        save_snapshot(driver, snapshot["result"], snapshot["as_of_date"])
    peak = history[peak_index(history)]
    driver.execute_query(queries.MARK_PEAK_SNAPSHOT, claim_id=claim_id,
                         peak_snapshot_id=f"{claim_id}-{peak['as_of_date'].isoformat()}")


def changed_snapshots(history):
    """The snapshots where the fired rules changed, plus the peak and the latest one.
    Each: {"as_of_date", "total_score", "band", "changes" (["+BI-2", "-AS-1"]), "is_peak"}."""
    rows = []
    peak = peak_index(history)
    previous_rules = []
    for index, snapshot in enumerate(history):
        result = snapshot["result"]
        rules = [rule["rule_id"] for rule in result["fired_rules"]]
        if index > 0 and rules == previous_rules and index != peak and index != len(history) - 1:
            continue                  # nothing changed on this date
        changes = [f"+{rule_id}" for rule_id in rules if rule_id not in previous_rules]
        changes += [f"-{rule_id}" for rule_id in previous_rules if rule_id not in rules]
        rows.append({"as_of_date": snapshot["as_of_date"], "total_score": result["total_score"],
                     "band": result["band"], "changes": changes, "is_peak": index == peak})
        previous_rules = rules
    return rows


def history_lines(claim_id, history):
    """One line per snapshot where the fired rules changed, then the peak and the trend."""
    lines = [f"Score history of {claim_id}: {len(history)} event dates (one snapshot each).",
             f"{'As of':<11} {'Score':>6}  {'Band':<10} Rules fired (+ new, - stopped)"]
    for row in changed_snapshots(history):
        marker = "  <- peak" if row["is_peak"] else ""
        lines.append(f"{row['as_of_date'].isoformat():<11} {row['total_score']:>6}  {row['band']:<10} "
                     f"{' '.join(row['changes']) or '(no change)'}{marker}")
    peak = history[peak_index(history)]
    lines.append(f"Peak: {peak['result']['total_score']} on {peak['as_of_date']}. "
                 f"Trend over the last {config.TREND_DAYS} days: {trend_of(history)}.")
    return lines
