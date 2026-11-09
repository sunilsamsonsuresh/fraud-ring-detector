"""The Challenger's checks (PLAN-v2.md A8, V11): plain code makes the list of challenges.

run_challenge_checks reads the facts each check needs, applies the fixed adjustments
(adjustments.py) one by one, and scores again after each one. So every challenge says
exactly which rules it changed. The two "note" checks change nothing.

| Check            | Effect                                              |
| same incident    | links inside the incident are not network evidence |
| family link      | NL-1 does not count for links to family members     |
| busy provider    | a link through a busy clinic or law firm only does not count |
| same proof twice | the points of one finding count once                |
| weak proof       | a rule on Low confidence findings only does not count |
| common rule      | note only: the rule fires on more than 25% of claims |
| low coverage     | note only: "not fully examined"                     |
"""

from src import config
from src.graph import queries
from src.scoring import adjustments
from src.scoring.as_of import facts_as_of
from src.scoring.engine import run_rules, score_rule_results

FAMILY_LINK_KINDS = ["phone", "address"]


def fired_rule_ids(rule_results):
    return [rule_id for rule_id, result in rule_results.items() if result["status"] == "fired"]


def read_incident_claim_ids(driver, claim_id):
    records, _, _ = driver.execute_query(queries.INCIDENT_CLAIM_IDS, claim_id=claim_id)
    return [record["claim_id"] for record in records]


def find_family_claim_ids(driver, raw):
    """Claims linked only by phone or address to a person with the same address and surname but a
    different birth date (A8 family link)."""
    network = raw["network"]
    candidates = sorted({link["linked_claim_id"] for link in network["direct_links"]
                         if link["kind"] in FAMILY_LINK_KINDS})
    if not candidates:
        return []
    other_links = {link["linked_claim_id"] for link in network["direct_links"] if link["kind"] not in FAMILY_LINK_KINDS}
    other_links |= {item["other_claim_id"] for item in network["copied_story"]}
    other_links |= {item["claim_id"] for item in network["repeat_claims"]}
    records, _, _ = driver.execute_query(queries.FAMILY_LINK_FACTS, claim_id=raw["claim_id"], other_claim_ids=candidates)
    family = []
    for record in records:
        if record["same_address"] and record["same_last_name"] and record["different_birth_date"] \
                and record["claim_id"] not in other_links:
            family.append(record["claim_id"])
    return family


def read_rule_fire_shares(driver):
    """{rule ID: share of scored claims that fire it}, from the latest snapshots (score-all)."""
    records, _, _ = driver.execute_query(queries.COUNT_SCORED_CLAIMS)
    scored = records[0]["count"]
    if scored == 0:
        return {}
    records, _, _ = driver.execute_query(queries.RULE_FIRE_COUNTS)
    return {record["rule_id"]: record["claim_count"] / scored for record in records}


def challenge(check, changed_rules, detail, effect):
    return {"check": check, "rules": changed_rules, "detail": detail, "effect": effect}


def run_challenge_checks(driver, raw):
    """Return (final score result after the fixed adjustments, list of challenges)."""
    challenges = []
    before = fired_rule_ids(run_rules(facts_as_of(raw)))

    incident_claim_ids = read_incident_claim_ids(driver, raw["claim_id"])
    steps = [("same incident", adjustments.drop_same_incident_links, [incident_claim_ids],
              "Links to claims of the same incident are not network evidence."),
             ("family link", adjustments.drop_family_links, [find_family_claim_ids(driver, raw)],
              "NL-1 does not count for links to family members."),
             ("busy provider", adjustments.drop_busy_provider_links, [],
              f"Links through a provider with more than {config.BUSY_PROVIDER_LIMIT} claims only do not count.")]
    current = raw
    previous_fired = before
    if incident_claim_ids:
        # Shown even when nothing is removed: the investigator sees that these links were not counted.
        challenges.append(challenge("same incident", [], incident_claim_ids,
                                    "Claims of the same incident; links between them are not network evidence "
                                    "(the network templates ignore them)."))
    for check, adjust, arguments, effect in steps:
        current, affected = adjust(current, *arguments)
        if affected:
            now_fired = fired_rule_ids(run_rules(facts_as_of(current)))
            changed = [rule_id for rule_id in previous_fired if rule_id not in now_fired]
            challenges.append(challenge(check, changed, affected, effect))
            previous_fired = now_fired

    facts = facts_as_of(current)
    rule_results = run_rules(facts)
    rule_results, same_proof = adjustments.drop_same_proof_twice(rule_results)
    if same_proof:
        challenges.append(challenge("same proof twice", same_proof, same_proof,
                                    "The points of one finding count once."))
    rule_results, weak = adjustments.drop_weak_proof(rule_results)
    if weak:
        challenges.append(challenge("weak proof", weak, weak, "A rule on Low confidence findings only does not count."))

    final = score_rule_results(rule_results)
    final["claim_id"] = raw["claim_id"]
    final["weak_findings"] = facts["weak_findings"]

    shares = read_rule_fire_shares(driver)
    common = [f"{rule_id} ({shares[rule_id]:.0%} of claims)" for rule_id in fired_rule_ids(rule_results)
              if shares.get(rule_id, 0) > config.COMMON_RULE_SHARE]
    if common:
        challenges.append(challenge("common rule", [], common,
                                    f"Note only: these rules fire on more than {config.COMMON_RULE_SHARE:.0%} of claims."))
    if final["coverage_pct"] < config.LOW_COVERAGE_PCT:
        challenges.append(challenge("low coverage", [], [f"coverage {final['coverage_pct']}%"],
                                    "Note only: not fully examined."))
    return final, challenges
