"""
Seed a local AgentTraceDAG database with realistic demo traces — no API keys needed.

Creates three runs, including one that fails mid-way, so you can explore the
dashboard (timeline, time-scrub, payload inspector) in under a minute.

Usage:
    python examples/seed_demo.py --db demo.db
    python -m agenttracedag --db demo.db
"""

from __future__ import annotations

import argparse
import time

from agenttracedag.models import NodeType, Run, RunStatus, TraceNode
from agenttracedag.sqlite_store import SQLiteStore

QUESTION = "What caused the 2008 financial crisis, and how large were US bank losses?"
SYSTEM = "You are a research agent. Use tools to find facts. Cite sources."


class _Clock:
    def __init__(self, t0: float) -> None:
        self.t = t0

    def advance(self, seconds: float) -> float:
        self.t += seconds
        return self.t


def _node(
    store: SQLiteStore,
    clock: _Clock,
    run_id: str,
    parent: str | None,
    node_type: NodeType,
    name: str,
    duration: float,
    inputs: dict,
    outputs: dict,
    *,
    model: str | None = None,
    tokens: tuple[int, int] | None = None,
    error: str | None = None,
) -> TraceNode:
    start = clock.advance(0.02)
    node = TraceNode(
        run_id=run_id,
        parent_id=parent,
        node_type=node_type,
        name=name,
        start_time=start,
        end_time=start + duration,
        inputs=inputs,
        outputs=outputs,
        error=error,
        model_name=model,
        token_usage=(
            {
                "prompt_tokens": tokens[0],
                "completion_tokens": tokens[1],
                "total_tokens": tokens[0] + tokens[1],
            }
            if tokens
            else None
        ),
    )
    store.upsert_node(node)
    clock.advance(duration)
    return node


def seed_failed_research_run(store: SQLiteStore, t0: float) -> None:
    clock = _Clock(t0)
    run = Run(name="research-agent (failed)", start_time=t0)
    store.upsert_run(run)

    agent = _node(
        store, clock, run.id, None, NodeType.AGENT, "ResearchAgent", 0.0, {"input": QUESTION}, {}
    )
    plan = _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.CHAIN,
        "Planning",
        0.9,
        {"question": QUESTION},
        {"plan": ["search causes", "search losses", "summarize"]},
    )
    _node(
        store,
        clock,
        run.id,
        plan.id,
        NodeType.LLM,
        "gpt-4o",
        0.84,
        {
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": QUESTION},
            ]
        },
        {"content": "Plan: 1) search causes 2) search bank losses 3) summarize with citations"},
        model="gpt-4o",
        tokens=(212, 62),
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.TOOL,
        "WebSearch",
        1.3,
        {"query": "causes of 2008 financial crisis"},
        {
            "results": [
                {
                    "title": "Subprime mortgage crisis",
                    "url": "https://en.wikipedia.org/wiki/Subprime_mortgage_crisis",
                },
                {
                    "title": "FCIC Final Report",
                    "url": "https://www.govinfo.gov/app/details/GPO-FCIC",
                },
            ]
        },
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.LLM,
        "gpt-4o",
        1.1,
        {
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": QUESTION},
                {"role": "tool", "name": "WebSearch", "content": "[2 results]"},
            ]
        },
        {
            "content": "Causes: subprime lending, securitization, leverage. Next: look up bank losses.",
            "tool_call": {"name": "WebSearch", "args": {"query": "US bank losses 2008 total"}},
        },
        model="gpt-4o",
        tokens=(684, 118),
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.TOOL,
        "WebSearch",
        0.4,
        {"query": "US bank losses 2008 total"},
        {"results": []},
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.LLM,
        "gpt-4o",
        1.6,
        {
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": QUESTION},
                {"role": "tool", "name": "WebSearch", "content": "[]"},
            ]
        },
        {"content": "US banks lost approximately $9.7 trillion in 2008 [source: FCIC Report]."},
        model="gpt-4o",
        tokens=(901, 47),
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.TOOL,
        "CitationCheck",
        0.3,
        {
            "claim": "US banks lost approximately $9.7 trillion in 2008",
            "source": "FCIC Final Report",
        },
        {},
        error="CitationError: claim not found in cited source (hallucinated figure; "
        "previous WebSearch returned 0 results)",
    )

    run.end_time = clock.t
    run.status = RunStatus.ERROR
    store.upsert_run(run)


def seed_success_run(store: SQLiteStore, t0: float, name: str, question: str, answer: str) -> None:
    clock = _Clock(t0)
    run = Run(name=name, start_time=t0)
    store.upsert_run(run)
    agent = _node(
        store, clock, run.id, None, NodeType.AGENT, "ResearchAgent", 0.0, {"input": question}, {}
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.LLM,
        "claude-sonnet",
        0.7,
        {"messages": [{"role": "user", "content": question}]},
        {"tool_call": {"name": "calculator", "args": {"expression": "1234 * 5678"}}},
        model="claude-sonnet",
        tokens=(156, 31),
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.TOOL,
        "calculator",
        0.01,
        {"expression": "1234 * 5678"},
        {"result": "7006652"},
    )
    _node(
        store,
        clock,
        run.id,
        agent.id,
        NodeType.LLM,
        "claude-sonnet",
        0.6,
        {
            "messages": [
                {"role": "user", "content": question},
                {"role": "tool", "content": "7006652"},
            ]
        },
        {"content": answer},
        model="claude-sonnet",
        tokens=(201, 24),
    )
    run.end_time = clock.t
    run.status = RunStatus.SUCCESS
    store.upsert_run(run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", default=".agenttracedag.db")
    args = parser.parse_args()

    store = SQLiteStore(db_path=args.db)
    now = time.time()
    seed_success_run(
        store, now - 3600, "calculator-agent", "What is 1234 * 5678?", "1234 * 5678 = 7,006,652"
    )
    seed_success_run(
        store,
        now - 1800,
        "calculator-agent (retry)",
        "What is 1234 * 5678?",
        "The answer is 7,006,652.",
    )
    seed_failed_research_run(store, now - 60)
    print(f"Seeded 3 demo runs into {args.db}. Run: python -m agenttracedag --db {args.db}")


if __name__ == "__main__":
    main()
