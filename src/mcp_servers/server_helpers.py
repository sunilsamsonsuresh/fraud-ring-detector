"""Code that all three MCP servers share.

A server tool does three things, always in this order:
1. It checks the value from the client (plain code, src/tools/checks.py). A bad value gives a message.
2. It opens the Neo4j connection, runs ONE plain tool, and closes the connection.
3. It returns one dict: {"facts", "notes", "sources"} or {"message", "sources": []}.

The servers do not repeat the safety checks. A client is an agent, so its values are not trusted.
Nothing from a client is ever a query. Values only go into named queries as parameters (CLAUDE.md, rule 11).
"""

from src.graph.connection import open_neo4j_driver
from src.tools.checks import run_for_claim


def finish(result):
    """Make sure the answer always has a "sources" list. A message has no sources, so the list is empty."""
    result.setdefault("sources", [])
    return result


def run_tool(tool_function, *arguments):
    """Open the driver, run tool_function(driver, *arguments), close the driver, return the answer.

    A problem with Neo4j (down, wrong password) becomes a message. The client sees the reason, not a crash."""
    try:
        driver = open_neo4j_driver()
    except RuntimeError as problem:
        return finish({"message": str(problem)})
    try:
        return finish(tool_function(driver, *arguments))
    finally:
        driver.close()


def run_tool_for_claim(claim_text, tool_function, *arguments):
    """Like run_tool, but the claim ID is checked first: tool_function(driver, claim_id, *arguments).

    A value that is not a claim ID gives a message, and no query runs."""

    def checked_tool(driver, claim_text_from_client):
        return run_for_claim(
            driver,
            claim_text_from_client,
            lambda driver, claim_id: tool_function(driver, claim_id, *arguments),
        )

    return run_tool(checked_tool, claim_text)


def run_checked_value(check_function, text, tool_function):
    """Check one value (a phone, a name), then run tool_function(driver, checked_value).

    check_function returns (value, None) or (None, message), like check_claim_id."""
    value, problem = check_function(text)
    if problem is not None:
        return finish({"message": problem})
    return run_tool(tool_function, value)
