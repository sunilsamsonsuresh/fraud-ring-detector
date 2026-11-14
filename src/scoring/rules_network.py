"""The yes/no checks of the rules about links between claims: NL-1, NL-2, NL-5 and NL-6.

NL means "network links". These rules look beyond one claim: does it share something with other claims?
NL-3 (same clinic and attorney) is in rules_tables.py.

The facts come from src/scoring/facts.py. Links between claims of the SAME incident are already
left out by the queries, because they are one accident and not a network (CLAUDE.md, rule 20).
A fired rule means "possible link, needs human review". It is never proof.
"""

from src import config
from src.scoring.rule_results import fired_or_not, not_evaluated
from src.scoring.rules_tables import MAX_LINKS_IN_PROOF


def days_for_months(months):
    """A month length in days. 12 months = 365 days. The data generator uses the same length."""
    return round(months * 365 / 12)


def link_texts(links):
    """Short texts like "C-1209 (phone: 555-0101)", sorted, without repeats, cut at a maximum."""
    texts = set()
    for link in links:
        texts.add(f"{link['linked_claim_id']} ({link['kind']}: {link['shared_value']})")
    return sorted(texts)[:MAX_LINKS_IN_PROOF]


def check_nl_1(facts):
    """Shared phone or address with a claim of a different incident."""
    links = []
    for link in facts["direct_links"]:
        if link["kind"] in ["phone", "address"]:
            links.append(link)
    return fired_or_not(len(links) > 0, {"links": link_texts(links)})


def check_nl_2(facts):
    """Repeat claimant: 2 or more other claims within 36 months of this loss."""
    window_days = days_for_months(config.REPEAT_CLAIM_MONTHS)
    close_claims = []
    for other in facts["repeat_claims"]:
        # abs(): an earlier claim and a later claim both count.
        if abs((other["loss_date"] - facts["loss_date"]).days) <= window_days:
            close_claims.append(f"{other['claim_id']} (loss {other['loss_date']})")
    return fired_or_not(
        len(close_claims) >= config.REPEAT_CLAIM_OTHER_CLAIMS,
        {"other_claims_of_claimant": close_claims},
    )


def check_nl_4(facts):
    """Copied story: a story chunk of this claim is a near-copy of a chunk in a claim of another incident.

    The graph finds the copies with the stored embeddings (src/tools/link_tools.py). A score is a number
    from 0 to 1: 1 means the same meaning. Here plain code only checks if any copy was found."""
    if not facts["has_story_text"]:
        return not_evaluated("no story text (fnol, complaint or demand letter)")
    copies = facts["copied_story"]
    pairs = []
    for copy in copies[:MAX_LINKS_IN_PROOF]:
        pairs.append(
            f"{copy['document_id']} page {copy['page_number']} ~ {copy['other_document_id']} "
            f"page {copy['other_page_number']} ({copy['score']:.3f})"
        )
    return fired_or_not(
        len(copies) > 0,
        {
            "other_claims": sorted({copy["other_claim_id"] for copy in copies}),
            "copied_chunks": pairs,
        },
    )


def check_nl_5(facts):
    """Same law firm and same expert: linked to 3 or more claims whose suit was filed within 12 months."""
    if not facts["lawsuits"]:
        return not_evaluated("no lawsuit")
    window_days = days_for_months(config.FIRM_AND_EXPERT_MONTHS)
    linked_claim_ids = set()
    for link in facts["direct_links"]:
        if link["kind"] != "firm_and_expert":
            continue
        if (
            abs((link["linked_filed_date"] - link["source_filed_date"]).days)
            <= window_days
        ):
            linked_claim_ids.add(link["linked_claim_id"])
    return fired_or_not(
        len(linked_claim_ids) >= config.FIRM_AND_EXPERT_MIN_LAWSUITS,
        {
            "lawsuits_within_window": len(linked_claim_ids),
            "linked_claims": sorted(linked_claim_ids),
        },
    )


def check_nl_6(facts):
    """Large linked cluster: the claim sits in a group of 8 or more claims joined by direct links (3 hops)."""
    cluster = facts["cluster_claim_ids"]  # includes the claim itself
    proof = {"claims_in_group": len(cluster), "claims": cluster[:MAX_LINKS_IN_PROOF]}
    if len(cluster) > MAX_LINKS_IN_PROOF:
        # Say that the list is cut, so nobody reads the shorter list as the whole group.
        proof["claims_not_listed"] = len(cluster) - MAX_LINKS_IN_PROOF
    return fired_or_not(len(cluster) >= config.CLUSTER_MIN_CLAIMS, proof)


NETWORK_RULE_CHECKS = {
    "NL-1": check_nl_1,
    "NL-2": check_nl_2,
    "NL-4": check_nl_4,
    "NL-5": check_nl_5,
    "NL-6": check_nl_6,
}


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    import datetime

    loss = datetime.date(2025, 3, 1)
    filed = datetime.date(2025, 9, 1)
    sample_facts = {
        "loss_date": loss,
        "lawsuits": [
            {"lawsuit_id": "LS-1", "filed_date": filed, "limitation_deadline": filed}
        ],
        "direct_links": (
            [
                {
                    "linked_claim_id": "C-2001",
                    "kind": "phone",
                    "shared_value": "555-0101",
                }
            ]  # NL-1 fires
            + [
                {
                    "linked_claim_id": f"C-30{number}",
                    "kind": "firm_and_expert",
                    "shared_value": "Firm + Expert",
                    "source_filed_date": filed,
                    "linked_filed_date": filed + datetime.timedelta(days=30 * number),
                }
                for number in range(1, 5)
            ]
        ),  # filed 30, 60, 90, 120 days apart: 4 inside 12 months
        "repeat_claims": [
            {"claim_id": "C-4001", "loss_date": loss - datetime.timedelta(days=200)},
            {"claim_id": "C-4002", "loss_date": loss + datetime.timedelta(days=400)},
            {"claim_id": "C-4003", "loss_date": loss + datetime.timedelta(days=2000)},
        ],  # too far
        "has_story_text": True,
        "copied_story": [
            {
                "document_id": "C-0000-fnol",
                "page_number": 1,
                "other_claim_id": "C-6001",
                "other_document_id": "C-6001-fnol",
                "other_page_number": 1,
                "score": 0.991,
            }
        ],  # NL-4 fires
        "cluster_claim_ids": [
            f"C-50{number:02d}" for number in range(9)
        ],  # 9 claims: NL-6 fires
    }
    for rule_id, check in NETWORK_RULE_CHECKS.items():
        print(rule_id, check(sample_facts))
