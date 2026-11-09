"""Agent 3: Evidence - GraphRAG text search (PLAN.md Step 7, PLAN-v2.md A8 and V8).

Input: state["claim_id"] and state["linked_claims"] (from the Graph Investigator).
No LLM here. Plain code finds the text; later agents read and explain it.

1. The claims to search = this claim + its linked claims. The graph decides, not the text.
2. For each fixed topic, find the closest chunks, in those claims only.
3. v2: find near-copies of this claim's story in claims of OTHER incidents, anywhere in the
   portfolio (the NL-4 template; copies inside one incident do not count).
4. v2: the quote behind each fired rule (the finding's quote, or the copied text for NL-4).
Every snippet keeps its source: claim, document, file name and page.
"""

import datetime

from src.graph.connection import open_neo4j_driver
from src.graph.network import find_copied_story
from src.graph.retrieval import count_chunks_of_claims, search_text_in_claims
from src.scoring.engine import score_claim

# topic -> the text we compare with the chunks. Each text is written the way such a
# document is written, because that finds the right documents much better than a short
# label. Tested: "how the accident happened" found 9 adjuster notes and 0 claimant
# stories in 10 results; the text below found 10 claimant stories.
EVIDENCE_TOPICS = {
    "accident_story": ("Description of the accident (claimant's words): I was stopped when another "
                       "vehicle struck my car"),
    "injuries_and_treatment": ("Treatment summary. Diagnosis: neck and back strain. Complaints at the initial "
                               "evaluation included pain and reduced range of motion. Over the course of the "
                               "visits, treatment consisted of therapy and exercise."),
    "lawyers_and_demands": ("Our client was injured in the collision. We demand payment of the policy limits. "
                            "Plaintiff seeks damages and attorney's fees."),
}
SNIPPETS_PER_TOPIC = 5
SNIPPET_CHARACTERS = 300


def make_snippet(result):
    return {
        "claim_id": result["claim_id"], "document_id": result["document_id"],
        "source": f"{result['file_name']}, page {result['page_number']}",
        "page_number": result["page_number"], "chunk_id": result["chunk_id"],
        "score": round(result["score"], 3), "text": result["text"][:SNIPPET_CHARACTERS],
    }


def make_copy(result):
    return {
        "document_id": result["document_id"], "page_number": result["page_number"],
        "other_claim_id": result["other_claim_id"], "other_document_id": result["other_document_id"],
        "other_page_number": result["other_page_number"], "score": round(result["score"], 3),
        "text": result["text"][:SNIPPET_CHARACTERS],
    }


def quotes_behind_fired_rules(result, copies):
    """[{"rule_id", "source", "quote"}] for each fired rule that rests on text."""
    quotes = []
    for rule in result["fired_rules"]:
        for finding in rule["proof"].get("findings", []):
            quotes.append({"rule_id": rule["rule_id"],
                           "source": f"{finding['document_id']}, page {finding['page_number']}",
                           "quote": finding["quote"]})
        if rule["rule_id"] == "NL-4" and copies:
            best = copies[0]
            quotes.append({"rule_id": "NL-4",
                           "source": f"{best['document_id']}, page {best['page_number']} ~ "
                                     f"{best['other_document_id']}, page {best['other_page_number']}",
                           "quote": best["text"][:SNIPPET_CHARACTERS]})
    return quotes


def evidence(state):
    claim_id = state["claim_id"]
    linked_claim_ids = []
    for entry in state.get("linked_claims", []):
        linked_claim_ids.append(entry["claim_id"])
    claim_ids_to_search = [claim_id] + linked_claim_ids

    driver = open_neo4j_driver()
    try:
        if count_chunks_of_claims(driver, [claim_id]) == 0:
            return {"error_message": f"Claim {claim_id} has no text chunks. "
                                     "Run: python main.py ingest-documents --chunks"}
        snippets_by_topic = {}
        for topic, description in EVIDENCE_TOPICS.items():
            results = search_text_in_claims(driver, description, claim_ids_to_search, SNIPPETS_PER_TOPIC)
            snippets_by_topic[topic] = [make_snippet(result) for result in results]
        copies = [make_copy(result) for result in find_copied_story(driver, claim_id)]
        # The rules are plain code and cheap, so Evidence runs them (without saving) to know
        # which rules fired. Risk Scoring scores again and saves the snapshot.
        current = score_claim(driver, claim_id, datetime.date.today(), save=False)
    finally:
        driver.close()

    return {
        "evidence_claim_ids": claim_ids_to_search,
        "evidence_snippets": snippets_by_topic,
        "copied_text": copies,
        "rule_quotes": quotes_behind_fired_rules(current, copies) if current else [],
    }


if __name__ == "__main__":
    # Manual check until the workflow exists (Step 9): python -m src.agents.evidence C-1037
    # Runs the Graph Investigator first (one cached LLM call), then this agent.
    import sys
    from src.agents.graph_investigator import graph_investigator
    state = {"claim_id": sys.argv[1]}
    state.update(graph_investigator(state))
    result = evidence(state)
    if "error_message" in result:
        print(result["error_message"])
        raise SystemExit(1)
    print(f"Searched {len(result['evidence_claim_ids'])} claims (this claim + linked claims).")
    for topic, snippets in result["evidence_snippets"].items():
        print(f"\n== {topic}")
        for snippet in snippets:
            print(f"  [{snippet['score']}] {snippet['claim_id']}  {snippet['source']}")
            print(f"      {snippet['text'][:160]}...")
    other_claims = sorted({copy["other_claim_id"] for copy in result["copied_text"]})
    print(f"\n== copied text: {len(result['copied_text'])} chunk pairs with {len(other_claims)} other claims: "
          + ", ".join(other_claims))
    for copy in result["copied_text"][:5]:
        print(f"  [{copy['score']}] {copy['document_id']} p{copy['page_number']}  ~  "
              f"{copy['other_document_id']} p{copy['other_page_number']}")
