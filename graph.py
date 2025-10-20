from __future__ import annotations
from typing import List, Dict, Any, TypedDict, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from agents import search_agent, fetch_agent, report_agent


class AppState(TypedDict):
    query: str
    region: str
    links: List[str]
    pages: List[Dict[str, Any]]
    prices: List[Dict[str, Any]]
    report: Optional[str]


def build_graph():
    graph = StateGraph(AppState)

    graph.add_node("search", search_agent)
    graph.add_node("fetch", fetch_agent)
    graph.add_node("report", report_agent)
    graph.set_entry_point("search")
    graph.add_edge("search", "fetch")
    graph.add_edge("fetch", "report")
    graph.add_edge("report", END)
    return graph.compile()  ##checkpointer=MemorySaver() inside compile
