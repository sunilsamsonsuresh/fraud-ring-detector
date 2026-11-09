"""The shared state that the agents pass along (CLAUDE.md, rule 5.5).

Each agent reads the state and returns a dict with only the fields it changes.
Later steps add their own fields here.

TypedDict: a normal dict, plus a list of the keys and value types it should have.
Python does not check it at run time, but editors and readers can see the shape.
total=False: no key is required, because the state fills up one agent at a time.
"""

from typing import TypedDict


class InvestigationState(TypedDict, total=False):
    # Input
    claim_id: str                    # the claim under investigation, for example "C-1037"

    # Set by Agent 1: Intake
    documents_read: int              # number of PDFs read for the claim
    entity_results: list             # one dict per entity found: status matched / unmatched / not_in_graph
    document_conflicts: list         # [{"document_id", "page_number", "field", "table_value", "document_value"}]
    findings: list                   # v2: checked findings [{"feature", "value", "confidence", "quote", "page_number", ...}]
    dropped_findings: list           # v2: findings plain code refused, each with its reason
    intake_warnings: list            # skipped pages, invented values, unreadable dates; plain text

    # Set by Agent 2: Graph Investigator
    graph_templates_chosen: list     # [{"name": ..., "hops": ...}] that passed the checks
    graph_plan_reason: str           # the LLM's one-sentence reason for its choice
    graph_queries_run: list          # [{"template", "parameters", "rows"}] for the report
    linked_claims: list              # [{"claim_id", "hop", "links": [...]}], see graph_investigator.py
    graph_warnings: list             # rejected choices, fallbacks; plain text

    # Set by Agent 3: Evidence
    evidence_claim_ids: list         # the claims whose text was searched (this claim + linked claims)
    evidence_snippets: dict          # {topic: [{"claim_id", "source", "page_number", "score", "text", ...}]}
    copied_text: list                # near-copies of this claim's text in linked claims, with both sources

    # Set by Agent 4: Litigation Analyst (runs only when a lawsuit exists)
    litigation_facts: dict           # own_lawsuit, related_lawsuits, near-deadline and similar-demand lists
    litigation_review: dict          # the LLM's {"assessment", "reason", "points"}, or None
    litigation_warnings: list

    # Set by Agent 5: Risk Scoring
    risk_signals: list               # [{"name", "count", "points", "max_points", "evidence": [{"source", ...}]}]
    risk_score: int                  # 0 to 100, plain Python, before the Challenger
    risk_level: str                  # "low", "medium" or "high"
    risk_explanation: str            # LLM summary + the fixed list of signals and sources
    risk_warnings: list

    # Set by Agent 6: Challenger
    challenger_review: dict          # {"innocent_explanations", "needs_more_evidence", "follow_up_question"}
    discounted_signals: list         # signal names with an accepted innocent explanation
    final_risk_score: int            # the score after the discounts
    final_risk_level: str
    challenger_warnings: list
    loop_count: int                  # times the Challenger sent the case back (at most MAX_INVESTIGATION_LOOPS)

    # Set by Agent 7: Report Writer, and by the save step
    report_text: str
    report_warnings: list
    saved_summary: str               # the one line saved on the Claim node
    report_file: str

    # Set by any agent that cannot go on (for example, the claim does not exist)
    error_message: str
