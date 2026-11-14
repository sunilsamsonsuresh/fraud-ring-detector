"""MCP server 2: the links between claims in the graph.

Run it:  .venv/bin/python -m src.mcp_servers.graph_links_server
See claim_records_server.py for how an MCP server works.

A link is a possible link that needs human review. It is never proof that a person committed fraud
(CLAUDE.md, rule 14). Links inside one incident are not counted (rule 20). All tools only read.
Local search uses the tools about ONE claim or entity. Global search uses the tools about ALL claims:
the communities (groups of linked claims) and the shared groups.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from src.mcp_servers.server_helpers import (
    run_checked_value,
    run_tool,
    run_tool_for_claim,
)
from src.tools.checks import (
    check_community_or_claim,
    check_group_kind,
    check_name,
    check_phone,
)
from src.tools.community_tools import get_community as read_community
from src.tools.community_tools import list_communities as read_communities
from src.tools.entity_tools import get_entity_context as read_entity_context
from src.tools.group_tools import find_shared_groups as list_shared_groups
from src.tools.link_tools import get_claim_neighbourhood as read_claim_neighbourhood
from src.tools.search_tools import claims_linked_to_name, claims_with_phone

server = FastMCP(
    "fraud-graph-links",
    log_level="WARNING",  # only warnings and errors: the chat stays readable
    instructions="Links between personal auto injury claims. A link is a possible link that needs human "
    "review. It is never proof that a person committed fraud.",
)

READ_ONLY = ToolAnnotations(readOnlyHint=True)


@server.tool(annotations=READ_ONLY)
def get_claim_neighbourhood(claim_id: str) -> dict[str, Any]:
    """The other claims that ONE claim is linked to (shared phone, address, clinic and attorney, law firm
    and expert), with the reason for each link. Links inside the same accident are not counted.
    claim_id looks like C-1026."""
    return run_tool_for_claim(claim_id, read_claim_neighbourhood)


@server.tool(annotations=READ_ONLY)
def find_claims_sharing_phone(phone: str) -> dict[str, Any]:
    """The claims of every claimant with this phone number. phone: 7 or 10 digits, for example 713-555-2172."""
    return run_checked_value(check_phone, phone, claims_with_phone)


@server.tool(annotations=READ_ONLY)
def find_claims_linked_to_name(name: str) -> dict[str, Any]:
    """The claims linked to a clinic, repair shop, attorney or law firm with this name. If several names
    contain the text, the answer lists them and asks which one is meant."""
    return run_checked_value(check_name, name, claims_linked_to_name)


@server.tool(annotations=READ_ONLY)
def find_shared_groups(kind: str) -> dict[str, Any]:
    """Groups of claims across ALL claims that share the same phone, address, clinic and attorney, or law firm
    and expert. Use it when the question names no claim. kind is one of: phone, address, clinic_and_attorney,
    firm_and_expert. Biggest groups first."""
    return run_checked_value(check_group_kind, kind, list_shared_groups)


@server.tool(annotations=READ_ONLY)
def get_entity_context(name: str) -> dict[str, Any]:
    """Everything around ONE person, clinic, repair shop, attorney, law firm, expert, phone or address:
    its claims and its role in each, their saved scores, and the documents that mention it (with page).
    name: a name or part of it, a phone number, or a street address. Several matches give a list to pick from."""
    return run_checked_value(check_name, name, read_entity_context)


@server.tool(annotations=READ_ONLY)
def list_communities() -> dict[str, Any]:
    """The communities: groups of claims joined by strong links (shared phone, address, clinic and attorney,
    or law firm and expert), the biggest first. Each comes with what its claims share, their score bands,
    and a short report. Use it for questions about rings, groups or patterns across ALL claims."""
    return run_tool(read_communities)


@server.tool(annotations=READ_ONLY)
def get_community(community_or_claim_id: str) -> dict[str, Any]:
    """ONE community with all its claims, what they share, their highest scores and its report.
    community_or_claim_id is a community ID like COM-01, or a claim ID like C-1088 (its community)."""
    return run_checked_value(
        check_community_or_claim, community_or_claim_id, read_community
    )


if __name__ == "__main__":
    server.run()  # the default transport is stdio
