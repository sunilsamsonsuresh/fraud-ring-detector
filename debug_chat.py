"""Run the real chat and print each step. For learning and debugging.

Run:  .venv/bin/python debug_chat.py                          (asks the QUESTIONS below)
      .venv/bin/python debug_chat.py "Why is C-1088 High?"    (asks your question)
Needs: Neo4j running and ANTHROPIC_API_KEY in .env.

It is the same chat as `python main.py chat`, with two differences:
- It uses the cheap model, so one question costs about one cent.
- After each step, it prints which part of the chat ran and what that part added.
"""

import json
import sys
import uuid

from langchain_core.messages import HumanMessage
from neo4j.exceptions import DriverError, Neo4jError

from src import config
from src.workflow import build_chat_workflow

# Asked one after the other in ONE session, so the second question can refer to the first.
QUESTIONS = [
    "Why is C-1088 High?",
    "What do its documents say about the treatment?",
]
USE_CHEAP_MODEL = True  # False: the strong model of the real chat (costs more)


def print_new_message(message):
    """Print the message that one step added to the conversation."""
    if message.type == "tool":
        # A search agent answers the planner with JSON. "findings" is its short summary.
        result = json.loads(message.content)
        print("  findings:", result["findings"])
    elif message.tool_calls:
        # The planner asks a search agent. The agent's name is the tool name.
        tool_call = message.tool_calls[0]
        print("  asks:", tool_call["name"])
        print("  task:", tool_call["args"].get("task", ""))
    else:
        # The planner's note, or the answer writer's reply.
        print("  text:", message.text)


def ask_question(graph, session, question):
    print("\n" + "=" * 70)
    print("QUESTION:", question)
    step_names = []
    # stream() runs the chat like invoke(). The difference: after each step it gives back
    # {step name: what the step added}, so we can print it.
    for step in graph.stream(
        {"messages": [HumanMessage(question)]}, session, stream_mode="updates"
    ):
        for step_name, step_output in step.items():
            step_names.append(step_name)
            print(f"\n--- Step {len(step_names)}: {step_name} finished. It added:")
            print_new_message(step_output["messages"][-1])
    print("\nPATH:", " -> ".join(step_names))


def main():
    if USE_CHEAP_MODEL:
        # Only for this script. The real chat always uses the strong model.
        config.STRONG_MODEL_NAME = config.CHEAP_MODEL_NAME
    print("Model:", config.STRONG_MODEL_NAME)

    questions = QUESTIONS
    if len(sys.argv) > 1:
        questions = [" ".join(sys.argv[1:])]

    graph = build_chat_workflow()
    # One session = one memory. LangGraph keeps the messages of each thread_id.
    session = {"configurable": {"thread_id": str(uuid.uuid4())}}
    try:
        for question in questions:
            ask_question(graph, session, question)
    except (RuntimeError, Neo4jError, DriverError) as error:
        print("Error:", error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
