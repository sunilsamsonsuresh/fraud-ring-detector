"""The MCP client: how an agent reaches our servers. It is the only way from an agent to the data.

use_server:          start a server as a child process, list its tools, call them, stop it.
call_mcp_tool:       call ONE tool and return its answer as a dict.
work_on_task:        a specialist agent works on one task: the strong LLM picks tools from the agent's own
                     list, this code runs them through MCP, and the LLM writes its findings.
answer_planner_task:  the node code that every search agent shares (local search, document search, scorer, ...).
From the terminal you can call a tool by hand, to see what a server returns.

Run:  .venv/bin/python -m src.mcp_servers.call_server_tool claim_records_server get_claim_score claim_id=C-1088
"""

import asyncio
import json
import os
import sys

from langchain_core.messages import HumanMessage, ToolMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src import config
from src.llm import ask_llm_with_tools

# The module names of our four servers (the agents pass one of them to call_mcp_tool).
CLAIM_RECORDS_SERVER = "src.mcp_servers.claim_records_server"
GRAPH_LINKS_SERVER = "src.mcp_servers.graph_links_server"
DOCUMENT_SEARCH_SERVER = "src.mcp_servers.document_search_server"
QUERY_SERVER = "src.mcp_servers.query_server"
ALL_SERVERS = [
    CLAIM_RECORDS_SERVER,
    GRAPH_LINKS_SERVER,
    DOCUMENT_SEARCH_SERVER,
    QUERY_SERVER,
]

# Every tool an agent may use: tool name -> the server that has it. All of them only read.
TOOL_SERVERS = {
    "get_claim_record": CLAIM_RECORDS_SERVER,
    "get_claim_score": CLAIM_RECORDS_SERVER,
    "list_claims_by_score": CLAIM_RECORDS_SERVER,
    "get_claim_neighbourhood": GRAPH_LINKS_SERVER,
    "find_claims_sharing_phone": GRAPH_LINKS_SERVER,
    "find_claims_linked_to_name": GRAPH_LINKS_SERVER,
    "find_shared_groups": GRAPH_LINKS_SERVER,
    "search_claim_documents": DOCUMENT_SEARCH_SERVER,
    "get_entity_context": GRAPH_LINKS_SERVER,
    "get_claim_findings": DOCUMENT_SEARCH_SERVER,
    "search_all_documents": DOCUMENT_SEARCH_SERVER,
    "list_communities": GRAPH_LINKS_SERVER,
    "get_community": GRAPH_LINKS_SERVER,
    "get_graph_map": QUERY_SERVER,
    "run_read_query": QUERY_SERVER,
}
MAX_TOOL_ROUNDS = (
    5  # rounds of tool calls for one task. More costs too much: the agent stops.
)
TOOL_DEFINITIONS = {}  # tool name -> its definition for the LLM. Read once from the servers.


def use_server(server_module, calls):
    """Start the server, list its tools, run the calls [(tool name, arguments)], stop the server.

    Return (the tools, the list of results). A tool has .name, .description and .annotations.
    A result has .isError and .structuredContent (a dict)."""

    async def talk_to_server():
        # stdio_client starts the server as a child process: python <the server file>.
        # We start the FILE, not "python -m <module>": the VS Code debugger runs each child process
        # through itself, and its own "-m" cannot find our modules. PYTHONPATH lets the file
        # import "src...". The other settings hide the download bars of the embedding model.
        server_file = config.PROJECT_ROOT / (server_module.replace(".", "/") + ".py")
        quiet_environment = dict(
            os.environ,
            PYTHONPATH=str(config.PROJECT_ROOT),
            HF_HUB_DISABLE_PROGRESS_BARS="1",
            TQDM_DISABLE="1",
            TRANSFORMERS_VERBOSITY="error",
        )
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(server_file)],
            cwd=str(config.PROJECT_ROOT),
            env=quiet_environment,
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            results = []
            for tool_name, arguments in calls:
                results.append(await session.call_tool(tool_name, arguments))
            return listed.tools, results

    return asyncio.run(talk_to_server())


def call_mcp_tool(server_module, tool_name, arguments):
    """Call one tool of one server and return its answer: {"facts", "notes", "sources"} or {"message", "sources"}.

    Every call starts a new server (about one second). Simple and slow, but enough for now.
    A failure becomes {"message": ..., "sources": []}, so an agent never needs a try/except."""
    try:
        _, (result,) = use_server(server_module, [(tool_name, arguments)])
    except Exception as problem:  # noqa: BLE001 (on purpose: see the comment)
        # Many kinds of error can come from the process and async layers. An agent needs only the message.
        return {
            "message": f"The tool server {server_module.split('.')[-1]} could not be used: {problem}",
            "sources": [],
        }
    if result.isError or not isinstance(result.structuredContent, dict):
        return {"message": f"The tool {tool_name} returned an error.", "sources": []}
    return result.structuredContent


def tool_definitions(tool_names):
    """The definitions (name, description, arguments) of these tools, read from the MCP servers themselves."""
    if not TOOL_DEFINITIONS:
        for server_module in ALL_SERVERS:
            try:
                tools, _ = use_server(server_module, [])
            except Exception as problem:  # noqa: BLE001 (same reason as in call_mcp_tool)
                # RuntimeError: the agent node turns it into a clear "could not work" message.
                raise RuntimeError(
                    f"The tool server {server_module.split('.')[-1]} could not start: {problem}"
                )
            for tool in tools:
                TOOL_DEFINITIONS[tool.name] = {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
    return [TOOL_DEFINITIONS[name] for name in tool_names]


def short_result(answer):
    """One short word or phrase about a tool answer, for the chat log."""
    if "facts" in answer:
        return "ok"
    return "message: " + answer.get("message", "")[:80]


def work_on_task(task, agent_name, tool_names, system_prompt):
    """One specialist agent works on one task. Return (findings text, list of tool answers).

    A loop: the LLM asks for tools from tool_names; this code runs them through MCP and gives the answers
    back; the loop ends when the LLM writes its findings. Each tool answer keeps its sources.
    It prints each step, so the person can follow the work. Raises RuntimeError when the LLM cannot be used."""
    print(f"  [{agent_name}] tools it may use: {', '.join(tool_names)}")
    tools = tool_definitions(tool_names)
    messages = [HumanMessage(task)]
    tool_answers = []
    for _ in range(MAX_TOOL_ROUNDS):
        reply = ask_llm_with_tools(messages, tools, system_prompt)
        messages.append(reply)
        if not reply.tool_calls:
            print(f"  [{agent_name}] done after {len(tool_answers)} tool call(s)")
            return reply.text.strip(), tool_answers
        for tool_call in reply.tool_calls:
            arguments = ", ".join(
                f"{name}={value}" for name, value in tool_call["args"].items()
            )
            if tool_call["name"] in tool_names:
                answer = call_mcp_tool(
                    TOOL_SERVERS[tool_call["name"]],
                    tool_call["name"],
                    tool_call["args"],
                )
            else:
                answer = {
                    "message": f"There is no tool named {tool_call['name']}.",
                    "sources": [],
                }
            print(
                f"  [{agent_name}] calls {tool_call['name']}({arguments}) -> {short_result(answer)}"
            )
            tool_answers.append(
                {
                    "tool": tool_call["name"],
                    "arguments": tool_call["args"],
                    "answer": answer,
                }
            )
            messages.append(
                ToolMessage(
                    json.dumps(answer, default=str), tool_call_id=tool_call["id"]
                )
            )
    print(f"  [{agent_name}] stopped after {MAX_TOOL_ROUNDS} rounds of tool calls")
    return f"I stopped after {MAX_TOOL_ROUNDS} rounds of tool calls.", tool_answers


def answer_planner_task(state, agent_name, tool_names, system_prompt):
    """Node code of a specialist agent. It reads the task the planner gave it (the planner's last tool call)
    and answers with ONE ToolMessage: {"agent", "task", "findings", "tool_answers"} as JSON."""
    planner_call = state["messages"][-1].tool_calls[0]
    task = planner_call["args"].get("task", "")
    try:
        findings, tool_answers = work_on_task(
            task, agent_name, tool_names, system_prompt
        )
    except RuntimeError as problem:
        findings, tool_answers = f"The {agent_name} could not work: {problem}", []
        print(f"  [{agent_name}] could not work: {problem}")
    result = {
        "agent": agent_name,
        "task": task,
        "findings": findings,
        "tool_answers": tool_answers,
    }
    return {
        "messages": [
            ToolMessage(
                json.dumps(result, default=str), tool_call_id=planner_call["id"]
            )
        ]
    }


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python -m src.mcp_servers.call_server_tool <server file name> <tool name> name=value ..."
        )
        print(
            "Example: python -m src.mcp_servers.call_server_tool claim_records_server get_claim_score claim_id=C-1088"
        )
        return
    server_module = f"src.mcp_servers.{sys.argv[1]}"
    arguments = dict(pair.split("=", 1) for pair in sys.argv[3:])
    tools, (result,) = use_server(server_module, [(sys.argv[2], arguments)])
    print("Tools of this server:", [tool.name for tool in tools])
    if result.isError:
        print("The tool returned an error:", result.content)
        return
    print(json.dumps(result.structuredContent, indent=2))


if __name__ == "__main__":
    main()
