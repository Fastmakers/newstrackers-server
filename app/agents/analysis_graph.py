from langgraph.graph import END, StateGraph

from app.agents.nodes.analyze_relevance import analyze_relevance
from app.agents.nodes.analyze_resume import analyze_resume
from app.agents.nodes.generate_report import generate_report
from app.agents.nodes.match_keywords import match_keywords
from app.agents.state import AnalysisState


def _build_graph():
    graph = StateGraph(AnalysisState)

    graph.add_node("analyze_resume", analyze_resume)
    graph.add_node("match_keywords", match_keywords)
    graph.add_node("analyze_relevance", analyze_relevance)
    graph.add_node("generate_report", generate_report)

    graph.set_entry_point("analyze_resume")
    graph.add_edge("analyze_resume", "match_keywords")
    graph.add_edge("match_keywords", "analyze_relevance")
    graph.add_edge("analyze_relevance", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


# 싱글톤: import 시점에 한 번만 컴파일
resume_analysis_graph = _build_graph()
