"""MCP server 1: the stored data and the score of ONE claim.

Run it:  .venv/bin/python -m src.mcp_servers.claim_records_server
It talks over stdio (standard input and output): a client starts it as a child process and sends
requests. Do not print() in this file. stdout carries the protocol.

MCP (Model Context Protocol) is a standard way to offer tools to an AI program. The server lists its
tools with a name, a description and the arguments. A client can call only these tools.

FastMCP is the helper class of the official `mcp` package. @server.tool() turns a plain function into
an MCP tool: the function name is the tool name, the docstring is the description, and the type hints
are the argument rules. ToolAnnotations(readOnlyHint=True) tells clients that the tool changes nothing.

All three tools only read. get_claim_score works out the score now by the fixed rules (plain code).
list_claims_by_score reads the saved scores of all claims. No LLM is called.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from src.mcp_servers.server_helpers import run_checked_value, run_tool_for_claim
from src.tools.checks import check_band
from src.tools.claim_tools import get_claim_record as read_claim_record
from src.tools.portfolio_tools import list_claims_by_score as read_saved_scores
from src.tools.score_tools import get_claim_score as work_out_claim_score

server = FastMCP(
    "fraud-claim-records",
    log_level="WARNING",  # only warnings and errors: the chat stays readable
    instructions="Stored data and the rule-based score of one personal auto injury claim. A score is a pointer "
    "for a human reviewer. It is never a finding of fraud.",
)

READ_ONLY = ToolAnnotations(readOnlyHint=True)


@server.tool(annotations=READ_ONLY)
def get_claim_record(claim_id: str) -> dict[str, Any]:
    """The stored data of ONE claim: dates, treatment visits, payments, reserve and lawsuits.
    claim_id looks like C-1026. Returns facts, notes and sources."""
    return run_tool_for_claim(claim_id, read_claim_record)


@server.tool(annotations=READ_ONLY)
def get_claim_score(claim_id: str) -> dict[str, Any]:
    """The fraud-risk score of ONE claim: total, band, coverage, and every fired rule with its points and
    proof. The score is worked out now by fixed rules. Rules that could not run are listed.
    claim_id looks like C-1026."""
    return run_tool_for_claim(claim_id, work_out_claim_score)


@server.tool(annotations=READ_ONLY)
def list_claims_by_score(band: str) -> dict[str, Any]:
    """The SAVED scores of ALL claims (the newest snapshot of each claim, not worked out again): how many claims
    are in each band, and the claims with the highest scores. Use it when the question names no claim.
    band is one of: any, very high, high, medium, low. It filters the list of top claims."""
    return run_checked_value(check_band, band, read_saved_scores)


if __name__ == "__main__":
    server.run()  # the default transport is stdio
