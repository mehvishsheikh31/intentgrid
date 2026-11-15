"""The LangGraph workflow. LangGraph is the coordinator, not a fifth agent (rule A6.2).

START -> precheck -> (spam) spam_precheck_stop -> END
                  -> understanding -> (spam) spam_stop -> END
                                   -> risk -> route -> responder -> compliance
         compliance -> pass       -> finish_pass   -> END   (awaiting_approval)
                    -> revise     -> bump_revision -> responder
                    -> exhausted  -> finish_manual -> END   (needs_manual_reply)
"""
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from agents.compliance import run_compliance
from agents.responder import run_responder
from agents.risk import run_risk
from agents.understanding import run_understanding
from repositories.agent_runs import save_agent_run
from workflow import router
from workflow.state import WorkflowState

RECURSION_LIMIT = 40  # the longest real path is about 14 steps


def _agent_node(fn, db: Session):
    """Run an agent function (which edits a state dict) as a LangGraph node.
    LangGraph wants the node to return only what changed."""

    def run(state: WorkflowState) -> dict:
        working = dict(state)
        fn(working, db)
        return {k: v for k, v in working.items() if k not in state or state[k] != v}

    return run


def _save_skipped(db: Session, ticket_id: int, names: tuple[str, ...], reason: str) -> None:
    for name in names:
        save_agent_run(
            db, ticket_id=ticket_id, agent_name=name, attempt_no=1, output_json=None,
            llm_calls=0, duration_ms=0, status="skipped", error=reason,
        )


def build_graph(db: Session):
    def precheck(state: WorkflowState) -> dict:
        if router.is_obvious_spam(state.get("subject", ""), state.get("redacted_message", "")):
            _save_skipped(
                db, state["ticket_id"],
                ("understanding", "risk", "responder", "compliance"), "spam pre-check",
            )
            return {"route": "spam_precheck", "status": "needs_manual_reply"}
        return {}

    def spam_stop(state: WorkflowState) -> dict:
        _save_skipped(db, state["ticket_id"], ("risk", "responder", "compliance"), "spam detected")
        return {"status": "needs_manual_reply"}

    def set_route(state: WorkflowState) -> dict:
        return {"route": router.decide_route(state)}

    def bump_revision(state: WorkflowState) -> dict:
        return {"revision_count": state.get("revision_count", 0) + 1}

    graph = StateGraph(WorkflowState)
    graph.add_node("precheck", precheck)
    graph.add_node("understanding", _agent_node(run_understanding, db))
    graph.add_node("spam_stop", spam_stop)
    graph.add_node("risk", _agent_node(run_risk, db))
    graph.add_node("route", set_route)
    graph.add_node("responder", _agent_node(run_responder, db))
    graph.add_node("compliance", _agent_node(run_compliance, db))
    graph.add_node("bump_revision", bump_revision)
    graph.add_node("finish_pass", lambda state: {"status": "awaiting_approval"})
    graph.add_node("finish_manual", lambda state: {"status": "needs_manual_reply"})

    graph.add_edge(START, "precheck")
    graph.add_conditional_edges(
        "precheck", router.route_after_precheck, {"spam": END, "analyse": "understanding"}
    )
    graph.add_conditional_edges(
        "understanding", router.route_after_understanding,
        {"spam": "spam_stop", "continue": "risk"},
    )
    graph.add_edge("spam_stop", END)
    graph.add_edge("risk", "route")
    graph.add_edge("route", "responder")
    graph.add_edge("responder", "compliance")
    graph.add_conditional_edges(
        "compliance", router.route_after_compliance,
        {"pass": "finish_pass", "revise": "bump_revision", "exhausted": "finish_manual"},
    )
    graph.add_edge("bump_revision", "responder")
    graph.add_edge("finish_pass", END)
    graph.add_edge("finish_manual", END)
    return graph.compile()


def run_workflow(db: Session, state: WorkflowState) -> WorkflowState:
    """Run the whole graph for one ticket and return the final state."""
    return build_graph(db).invoke(state, config={"recursion_limit": RECURSION_LIMIT})
