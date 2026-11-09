"""Printable text for the V15 evaluation. Plain code only, so the text is the same on every run."""

from src.evaluation.layers import LAYER_NAMES, LAYERS


def percent(value):
    return "-" if value is None else f"{100 * value:.0f}%"


def pair(flagged_and_all):
    flagged, all_count = flagged_and_all
    return f"{flagged}/{all_count}"


def layer_table_lines(metrics_by_layer, claim_count):
    lines = [f"Layer table: test split, {claim_count} claims. 'Medium+' = band Medium or above; 'High+' = High or above.",
             f"{'Layer':<26} {'Prec M+':>8} {'Recall M+':>10} {'Prec H+':>8} {'Recall H+':>10} {'Top-25':>7} "
             f"{'Lookalike alarms M+':>20}"]
    for layer in LAYERS:
        metrics = metrics_by_layer[layer]
        alarms = metrics["lookalike_false_alarms_at_medium"]
        alarm_count = sum(flagged for flagged, _ in alarms.values())
        lookalike_count = sum(all_count for _, all_count in alarms.values())
        lines.append(f"{LAYER_NAMES[layer]:<26} {percent(metrics['at_medium']['precision']):>8} "
                     f"{percent(metrics['at_medium']['recall']):>10} {percent(metrics['at_high']['precision']):>8} "
                     f"{percent(metrics['at_high']['recall']):>10} {percent(metrics['precision_top_25']):>7} "
                     f"{f'{alarm_count}/{lookalike_count}':>20}")
    return lines


def recall_lines(metrics_by_layer):
    fraud_types = list(metrics_by_layer[LAYERS[0]]["recall_by_fraud_type_at_medium"])
    lines = ["Recall by fraud type at Medium+ (found / all):",
             f"{'Fraud type':<20} " + " ".join(f"{LAYER_NAMES[layer]:>26}" for layer in LAYERS)]
    for fraud_type in fraud_types:
        cells = [pair(metrics_by_layer[layer]["recall_by_fraud_type_at_medium"][fraud_type]) for layer in LAYERS]
        lines.append(f"{fraud_type:<20} " + " ".join(f"{cell:>26}" for cell in cells))
    return lines


def band_lines(metrics_by_layer):
    lines = ["Bands (fraud / honest):"]
    for layer in LAYERS:
        table = metrics_by_layer[layer]["band_table"]
        cells = [f"{band} {counts['fraud']}/{counts['honest']}" for band, counts in table.items()]
        lines.append(f"  {LAYER_NAMES[layer]:<26} " + ", ".join(cells))
    return lines


def agent_summary_lines(records):
    finished = [record for record in records if not record["error"]]
    lines = [f"Agent runs: {len(records)} claims, {len(finished)} finished, {len(records) - len(finished)} errors."]
    if not finished:
        return lines
    challenges = sum(record["challenges"] for record in finished)
    explained = sum(record["challenges_explained"] for record in finished)
    warning_totals = {}
    for record in finished:
        for key, count in record["warnings"].items():
            warning_totals[key] = warning_totals.get(key, 0) + count
    lines += [
        f"  Final score = plain-code score (c): {sum(record['matches_plain_code'] for record in finished)}/{len(finished)}",
        f"  Briefs with forbidden words: {sum(1 for record in finished if record['forbidden_words'])}; "
        f"with the closing sentence: {sum(record['has_closing_sentence'] for record in finished)}/{len(finished)}",
        f"  Rounds: 1 round {sum(record['rounds'] == 1 for record in finished)}, "
        f"2 rounds {sum(record['rounds'] == 2 for record in finished)}; "
        f"Litigation Analyst ran {sum(record['litigation_ran'] for record in finished)} times",
        f"  Challenger checks explained by the LLM: {explained}/{challenges}; "
        f"other innocent explanations: {sum(record['other_innocent_explanations'] for record in finished)}",
        "  Warnings by agent: " + ", ".join(f"{key} {count}" for key, count in warning_totals.items()),
        f"  New LLM calls: {sum(record['new_llm_calls'] for record in records)}, "
        f"cost ${sum(record['cost'] for record in records):.2f}, "
        f"time {sum(record['seconds'] for record in records):.0f} s",
    ]
    return lines


def router_lines(results):
    right = sum(result["intent_right"] for result in results)
    claim_right = sum(result["claim_id_right"] for result in results)
    lines = [f"Router: intent right {right}/{len(results)} ({percent(right / len(results))}); "
             f"claim ID right {claim_right}/{len(results)}"]
    for result in results:
        if not result["intent_right"] or not result["claim_id_right"]:
            lines.append(f"  WRONG: '{result['question']}' (current claim {result['current_case']}): expected "
                         f"{result['expected_intent']} {result['expected_claim_id']!r}, got "
                         f"{result['chosen_intent']} {result['chosen_claim_id']!r}")
    return lines
