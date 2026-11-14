"""The yes/no checks of the rules that use table dates and links: BI-5, BI-6 and NL-3.

A rule check is a plain function. It gets the facts of ONE claim (src/scoring/facts.py) and returns
a rule result (src/scoring/rule_results.py). The proof names the values that decided the answer,
so a human can check every result.

No database and no LLM here (CLAUDE.md, rules 16 and 18). The same facts always give the same answer.
Thresholds (12 visits, 30 days, 5 claims) are in config.py.
"""

from src import config
from src.scoring.rule_results import fired_or_not, not_evaluated

MAX_LINKS_IN_PROOF = 10  # a long list would fill the report


def check_bi_5(facts):
    """Attorney before first treatment: the attorney was hired before the first visit."""
    if facts["attorney_retained_date"] is None:
        return not_evaluated("no attorney on the claim")
    if not facts["visit_dates"]:
        return not_evaluated("no treatment visits")
    first_visit_date = facts["visit_dates"][0]  # facts.py sorts the visits by date
    return fired_or_not(
        facts["attorney_retained_date"] < first_visit_date,
        {
            "attorney_retained_date": facts["attorney_retained_date"],
            "first_visit_date": first_visit_date,
        },
    )


def check_bi_6(facts):
    """Heavy early treatment: more than 12 visits in the first 30 days after the loss date."""
    early_visits = 0
    for visit_date in facts["visit_dates"]:
        days_after_loss = (visit_date - facts["loss_date"]).days
        # A visit before the loss date is not early treatment, so it does not count.
        if 0 <= days_after_loss <= config.HEAVY_EARLY_TREATMENT_DAYS:
            early_visits += 1
    return fired_or_not(
        early_visits > config.HEAVY_EARLY_TREATMENT_VISITS,
        {
            "loss_date": facts["loss_date"],
            f"visits_in_first_{config.HEAVY_EARLY_TREATMENT_DAYS}_days": early_visits,
        },
    )


def check_nl_3(facts):
    """Same clinic and same attorney: linked through both to 5 or more other claims."""
    if facts["attorney_retained_date"] is None:
        return not_evaluated("no attorney on the claim")
    linked_claim_ids = set()
    link_texts = set()
    for link in facts["direct_links"]:
        if link["kind"] == "clinic_and_attorney":
            linked_claim_ids.add(link["linked_claim_id"])
            link_texts.add(
                f"{link['linked_claim_id']} (clinic_and_attorney: {link['shared_value']})"
            )
    return fired_or_not(
        len(linked_claim_ids) >= config.CLINIC_AND_ATTORNEY_MIN_CLAIMS,
        {
            "linked_claim_count": len(linked_claim_ids),
            "links": sorted(link_texts)[:MAX_LINKS_IN_PROOF],
        },
    )


# Rule ID -> its check. The engine looks a rule up here. A rule that is not here is "not evaluated".
TABLE_RULE_CHECKS = {"BI-5": check_bi_5, "BI-6": check_bi_6, "NL-3": check_nl_3}
