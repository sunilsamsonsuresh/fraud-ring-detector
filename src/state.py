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
    intake_skipped: bool             # v2: True when the claim was already read (ingest-documents ran)

    # Set by Agent 2: Graph Investigator
    graph_templates_chosen: list     # [{"name": ..., "hops": ...}] that passed the checks
    graph_plan_reason: str           # the LLM's one-sentence reason for its choice
    graph_queries_run: list          # [{"template", "parameters", "rows"}] for the report
    linked_claims: list              # [{"claim_id", "hop", "links": [...]}], see graph_investigator.py
    graph_warnings: list             # rejected choices, fallbacks; plain text

    # Set by Agent 3: Evidence
    evidence_claim_ids: list         # the claims whose text was searched (this claim + linked claims)
    evidence_snippets: dict          # {topic: [{"claim_id", "source", "page_number", "score", "text", ...}]}
    copied_text: list                # v2: near-copies of this claim's story in claims of OTHER incidents
    rule_quotes: list                # v2: [{"rule_id", "source", "quote"}] the text behind each fired rule

    # Set by Agent 4: Litigation Analyst (runs only when a lawsuit exists)
    litigation_facts: dict           # own_lawsuit, related_lawsuits, near-deadline and similar-demand lists
    litigation_review: dict          # the LLM's {"assessment", "reason", "summary", "points"}, or None
    litigation_warnings: list

    # Set by Agent 5: Risk Scoring
    score_result: dict               # v2: the engine result (scores, band, coverage, fired rules with proof)
    risk_score: float                # 0 to 100, plain Python, before the Challenger
    risk_level: str                  # v2: the band, "Low", "Medium", "High" or "Very High"
    risk_summary: str                # v2: the LLM's 3-sentence summary of the fired rules
    risk_explanation: str            # the summary + every rule with its points and proof
    risk_warnings: list

    # Set by Agent 6: Challenger
    challenges: list                 # v2: [{"check", "rules", "detail", "effect", "explanation"}] from plain code
    challenger_review: dict          # {"check_explanations", "other_innocent_explanations", "needs_more_evidence",
                                     #  "follow_up_question"}; words only, they change no points
    final_score_result: dict         # v2: the engine result after the fixed adjustments
    final_risk_score: float          # the score after the fixed adjustments
    final_risk_level: str            # the band after the fixed adjustments
    challenger_warnings: list
    loop_count: int                  # times the Challenger sent the case back (at most MAX_INVESTIGATION_LOOPS)

    # Set by Agent 7: Report Writer, and by the save step
    report_brief: dict               # v2: the referral brief (saved as data/reports/<claim>.json)
    report_text: str
    report_warnings: list
    saved_summary: str               # the one line saved on the Claim node
    report_file: str

    # Set by the caller and by Human approval (V13)
    approval_wanted: bool            # True when the run pauses for the investigator after the report
    human_decision: str              # "approve", "reject" or "more"
    human_reason: str                # the investigator's reason (needed for reject and more)
    human_request_count: int         # times the investigator asked for more (at most MAX_HUMAN_REQUESTS)
    investigator_request: str        # the investigator's question for the next round (Graph Investigator)
    decision_record: dict            # the line saved in data/decisions.jsonl

    # Set by any agent that cannot go on (for example, the claim does not exist)
    error_message: str


class QuestionState(TypedDict, total=False):
    """The state of the question graph for `ask` and `chat` (V14). A second TypedDict, because a
    question is not an investigation: it shares no fields with InvestigationState."""
    question: str                    # the user's question, as typed. Data, never instructions.
    current_case: str                # the claim the chat is about; kept between questions of one chat
    route: dict                      # the Question Router's choice: {"intent", "claim_id", "rule_id", ...}
    router_warnings: list
    parameters: dict                 # the values after the plain-code checks
    tool_result: dict                # {"facts", "notes", "sources"} or {"message"}; None before the tool runs
    answer: str                      # the text shown to the user, with sources
    answer_warnings: list
