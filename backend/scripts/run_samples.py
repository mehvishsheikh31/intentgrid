"""Step 4.11: run the 12 sample messages through the full pipeline with REAL Gemini calls.

Examples (run from the backend folder):
  python scripts\\run_samples.py                       all 12, throwaway in-memory database
  python scripts\\run_samples.py --start 1 --count 6   first batch of 6 (the free limit is 500 calls a day)
  python scripts\\run_samples.py --start 7 --count 6   second batch
  python scripts\\run_samples.py --db neon             save the tickets in your real database (dashboard demo data)
  python scripts\\run_samples.py --show-drafts         also print every draft

Results are saved in data/sample_run_results.json, so batches add up to one summary.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: F401,E402
from app.db import Base, SessionLocal  # noqa: E402
from app.schemas import ContactSubmission  # noqa: E402
from repositories.agent_runs import list_agent_runs  # noqa: E402
from repositories.policies import get_policy, upsert_policy  # noqa: E402
from repositories.tickets import create_ticket, get_ticket  # noqa: E402
from seed_policies import load_sample_policy  # noqa: E402
from workflow.runner import process_ticket  # noqa: E402

SAMPLES_FILE = ROOT / "data" / "sample_messages.json"
RESULTS_FILE = ROOT / "data" / "sample_run_results.json"


def summarize(rows: list[dict]) -> dict:
    """Average LLM calls overall and by route, plus failures."""
    calls = [r["llm_calls"] for r in rows]
    by_route: dict[str, list[int]] = {}
    for r in rows:
        by_route.setdefault(r["route"], []).append(r["llm_calls"])
    return {
        "messages": len(rows),
        "total_calls": sum(calls),
        "average_calls": round(sum(calls) / len(calls), 2) if calls else 0,
        "max_calls": max(calls) if calls else 0,
        "by_route": {
            route: {"messages": len(v), "average_calls": round(sum(v) / len(v), 2), "max_calls": max(v)}
            for route, v in by_route.items()
        },
        "failed": [r["id"] for r in rows if r["status"] == "workflow_failed"],
        "incomplete": [r["id"] for r in rows if not r["complete"]],
    }


def route_label(outcome, ticket) -> str:
    if outcome.status == "workflow_failed":
        return "failed"
    if outcome.route in ("spam_precheck", "simple", "risky"):
        return outcome.route
    return "spam_llm" if ticket.is_spam else "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["memory", "neon"], default="memory")
    ap.add_argument("--start", type=int, default=1, help="first message number (1-based)")
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--pause", type=float, default=8.0, help="seconds between messages")
    ap.add_argument("--show-drafts", action="store_true")
    args = ap.parse_args()

    samples = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    chosen = samples[args.start - 1: args.start - 1 + args.count]
    print(f"Running {len(chosen)} message(s), database: {args.db}. Estimated Gemini calls: about {len(chosen) * 3}.")

    if args.db == "memory":
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        db = Session(bind=engine, expire_on_commit=False)
        upsert_policy(db, load_sample_policy())
    else:
        db = SessionLocal()
        if get_policy(db) is None:
            sys.exit("No policy in the database. Run: python scripts\\seed_policies.py")

    saved = json.loads(RESULTS_FILE.read_text(encoding="utf-8")) if RESULTS_FILE.exists() else {}
    header = f"{'#':>2} {'label':24} {'status':18} {'route':13} {'category':16} {'urg':>3} {'loss':6} {'prio':>5} {'rev':>3} {'calls':>5} {'sec':>5}  check"
    print("\n" + header)
    print("-" * len(header))

    for i, m in enumerate(chosen):
        ticket = create_ticket(
            db,
            ContactSubmission(name=m["name"], email=m["email"], phone=m["phone"], category=m["category"],
                              subject=m["subject"], message=m["message"]),
        )
        started = time.perf_counter()
        outcome = process_ticket(db, ticket.id)
        seconds = round(time.perf_counter() - started, 1)
        t = get_ticket(db, ticket.id)
        runs = list_agent_runs(db, ticket.id)
        complete = bool(t.category) and (
            bool(t.is_spam) or (t.urgency_score is not None and bool(t.loss_risk) and bool(t.draft_reply))
        )
        row = {
            "id": m["id"], "label": m["label"], "db": args.db, "status": outcome.status,
            "route": route_label(outcome, t), "category": t.category,
            "category_ok": t.category in m["expected_categories"],
            "urgency": t.urgency_score, "loss_risk": t.loss_risk, "priority": t.priority_score,
            "revisions": outcome.revision_count, "llm_calls": outcome.llm_calls, "seconds": seconds,
            "agent_runs": len(runs), "complete": complete, "error": outcome.error,
        }
        saved[str(m["id"])] = row
        check = "OK" if row["category_ok"] and complete else "CHECK"
        print(f"{m['id']:>2} {m['label'][:24]:24} {row['status']:18} {row['route']:13} {str(row['category']):16} "
              f"{str(row['urgency'] or '-'):>3} {str(row['loss_risk'] or '-'):6} "
              f"{str(round(row['priority']) if row['priority'] is not None else '-'):>5} "
              f"{row['revisions']:>3} {row['llm_calls']:>5} {seconds:>5}  {check}"
              + (f"  ERROR: {outcome.error}" if outcome.error else ""))
        if args.show_drafts and t.draft_reply:
            print("   draft:", t.draft_reply.replace("\n", " "))
        RESULTS_FILE.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
        if i < len(chosen) - 1:
            time.sleep(args.pause)

    s = summarize(list(saved.values()))
    print("\n=========== SUMMARY (all saved results) ===========")
    print(f"messages: {s['messages']}   total calls: {s['total_calls']}   "
          f"average calls per message: {s['average_calls']}   max: {s['max_calls']}")
    for route, info in sorted(s["by_route"].items()):
        print(f"  {route:14} messages={info['messages']}  average calls={info['average_calls']}  max={info['max_calls']}")
    print(f"failed: {s['failed'] or 'none'}   incomplete: {s['incomplete'] or 'none'}")
    print(f"saved to {RESULTS_FILE}")
    print("Expected: spam_precheck 0 calls, simple 2, risky 3, worst case 7 or fewer.")
    print("Anything marked CHECK, failed or incomplete goes into the bug log (Part D2).")


if __name__ == "__main__":
    main()
