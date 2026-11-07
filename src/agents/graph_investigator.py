"""Agent 2: Graph Investigator (PLAN.md, Step 5).

Input: state["claim_id"]. Output: the claims linked to it, and why.

1. Plain code reads a short profile of the claim from Neo4j (no profile -> error).
2. The cheap LLM sees the profile and the template list, and answers with JSON.
3. Plain code keeps only allowed template names and valid hop numbers.
   Bad JSON or no valid choice -> run the six basic templates.
4. Plain code runs the templates and groups the links by linked claim.
"""

import json

from src import config
from src.graph import investigation, queries
from src.graph.connection import open_neo4j_driver
from src.llm import ask_llm

SYSTEM_PROMPT = ("You help an insurance claims investigator choose graph searches. "
                 "You can only choose from the list you are given. Answer with JSON only.")

CHOOSE_TEMPLATES_PROMPT = """Claim profile (from the claims database):
{claim_profile}

Searches you can choose:
{template_list}

Choose the searches that can show if this claim is linked to other claims.
Skip searches that cannot apply (for example, the expert search when the claim has no expert).
Answer with this JSON only:
{{"templates": [{{"name": "claims_sharing_phone"}}, {{"name": "expand_linked_claims", "hops": 2}}],
 "reason": "one short sentence"}}"""

MAX_ANSWER_TOKENS = 1000


def read_claim_profile(driver, claim_id):
    records, _, _ = driver.execute_query(queries.CLAIM_PROFILE, claim_id=claim_id)
    if not records:
        return None
    return dict(records[0])


def build_prompt(claim_profile):
    profile_lines = []
    for key, value in claim_profile.items():
        profile_lines.append(f"- {key}: {value}")
    template_lines = []
    for name, (_, description) in investigation.LINK_TEMPLATES.items():
        template_lines.append(f"- {name}: {description}")
    template_lines.append(f"- {investigation.EXPAND_TEMPLATE_NAME} (needs \"hops\": "
                          f"{investigation.MIN_HOPS} to {investigation.MAX_HOPS}): "
                          f"{investigation.EXPAND_DESCRIPTION}")
    return CHOOSE_TEMPLATES_PROMPT.format(claim_profile="\n".join(profile_lines),
                                          template_list="\n".join(template_lines))


def parse_template_choices(answer_text):
    """Return (valid choices, reason, warnings). Never raises on bad LLM text."""
    # The model sometimes wraps JSON in ```json ... ```. Keep only the part between the braces.
    start, end = answer_text.find("{"), answer_text.rfind("}")
    try:
        answer = json.loads(answer_text[start:end + 1])
        requested = answer["templates"]
        if not isinstance(requested, list):
            raise TypeError("templates is not a list")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as problem:
        return [], "", [f"The LLM answer was not valid JSON ({problem})."]

    choices = []
    warnings = []
    names_already_chosen = set()
    for item in requested:
        name = item.get("name") if isinstance(item, dict) else None
        if name not in investigation.ALLOWED_TEMPLATE_NAMES:
            warnings.append(f"Rejected {item!r}: not an allowed template.")
            continue
        if name in names_already_chosen:
            continue
        choice = {"name": name}
        if name == investigation.EXPAND_TEMPLATE_NAME:
            try:
                investigation.check_hops(item.get("hops"))
            except ValueError as problem:
                warnings.append(f"Rejected {item!r}: {problem}")
                continue
            choice["hops"] = item["hops"]
        names_already_chosen.add(name)
        choices.append(choice)
    return choices, str(answer.get("reason", "")), warnings


def run_choices(driver, claim_id, choices):
    """Run each chosen template. Return (all links, a record of every query run)."""
    all_links = []
    queries_run = []
    for choice in choices:
        if choice["name"] == investigation.EXPAND_TEMPLATE_NAME:
            links = investigation.expand_linked_claims(driver, claim_id, choice["hops"])
            parameters = {"claim_id": claim_id, "hops": choice["hops"]}
        else:
            links = investigation.run_link_template(driver, choice["name"], [claim_id])
            for link in links:
                link["hop"] = 1
            parameters = {"claim_id": claim_id}
        all_links.extend(links)
        queries_run.append({"template": choice["name"], "parameters": parameters, "rows": len(links)})
    return all_links, queries_run


def group_links_by_claim(all_links):
    """One entry per linked claim: its smallest hop and every distinct reason."""
    claims = {}
    for link in all_links:
        claim_id = link["linked_claim_id"]
        if claim_id not in claims:
            claims[claim_id] = {"claim_id": claim_id, "hop": link["hop"], "links": []}
        entry = claims[claim_id]
        entry["hop"] = min(entry["hop"], link["hop"])
        reason = {"template": link["template"], "via_claim_id": link["source_claim_id"],
                  "shared_value": link["shared_value"]}
        if reason not in entry["links"]:   # the expansion repeats links that a basic template found
            entry["links"].append(reason)
    return sorted(claims.values(), key=lambda entry: (entry["hop"], entry["claim_id"]))


def graph_investigator(state):
    claim_id = state["claim_id"]
    driver = open_neo4j_driver()
    try:
        claim_profile = read_claim_profile(driver, claim_id)
        if claim_profile is None:
            return {"error_message": f"Claim {claim_id} was not found in the graph."}

        try:
            answer_text = ask_llm(build_prompt(claim_profile), config.CHEAP_MODEL_NAME,
                                  SYSTEM_PROMPT, max_tokens=MAX_ANSWER_TOKENS)
            choices, reason, warnings = parse_template_choices(answer_text)
        except RuntimeError as problem:   # API down, bad key: the plain-code part can still run
            choices, reason, warnings = [], "", [f"The LLM call failed: {problem}"]
        if not choices:
            choices = [{"name": name} for name in investigation.LINK_TEMPLATES]
            warnings.append("No valid template was chosen, so the six basic templates ran.")

        all_links, queries_run = run_choices(driver, claim_id, choices)
    finally:
        driver.close()

    return {
        "graph_templates_chosen": choices,
        "graph_plan_reason": reason,
        "graph_queries_run": queries_run,
        "linked_claims": group_links_by_claim(all_links),
        "graph_warnings": warnings,
    }


if __name__ == "__main__":
    # Manual check until the workflow exists (Step 9): python -m src.agents.graph_investigator C-1037
    import sys
    result = graph_investigator({"claim_id": sys.argv[1]})
    if "error_message" in result:
        print(result["error_message"])
        raise SystemExit(1)
    print("Chosen:", result["graph_templates_chosen"])
    print("Reason:", result["graph_plan_reason"])
    for warning in result["graph_warnings"]:
        print("Warning:", warning)
    for query_run in result["graph_queries_run"]:
        print(f"Ran {query_run['template']} {query_run['parameters']}: {query_run['rows']} rows")
    print(f"{len(result['linked_claims'])} linked claims:")
    for entry in result["linked_claims"]:
        reasons = sorted({f"{link['template']} = {link['shared_value']}" for link in entry["links"]})
        print(f"  hop {entry['hop']}  {entry['claim_id']}  " + "; ".join(reasons))
