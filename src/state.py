"""The shared state of the chat. Every agent of the LangGraph workflow reads it and writes to it.

The state has one key: messages, the whole conversation of this chat session.
It holds the person's questions, the planner's agent calls, the agents' findings and the replies.

TypedDict: a normal dict, plus a list of the keys and the type of each value. LangGraph reads the keys from it.
Annotated[list, add_messages] gives the key a "reducer": a node returns only its NEW messages,
and add_messages adds them to the end of the list. So nothing that was said is lost.
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
