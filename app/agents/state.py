from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Base state for LangGraph agents."""
    messages: Annotated[list, add_messages]
