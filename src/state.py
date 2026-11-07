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

    # Set by Agent 2: Graph Investigator
    graph_templates_chosen: list     # [{"name": ..., "hops": ...}] that passed the checks
    graph_plan_reason: str           # the LLM's one-sentence reason for its choice
    graph_queries_run: list          # [{"template", "parameters", "rows"}] for the report
    linked_claims: list              # [{"claim_id", "hop", "links": [...]}], see graph_investigator.py
    graph_warnings: list             # rejected choices, fallbacks; plain text

    # Set by any agent that cannot go on (for example, the claim does not exist)
    error_message: str
