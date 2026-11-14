import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.analysis import get_or_run_analysis  # noqa: E402
from workflow.redact import redact  # noqa: E402
from workflow.state import new_state  # noqa: E402

NAME, EMAIL = "Rahul Sharma", "rahul.sharma@example.com"

# (label, allowed categories, subject, message)
CASES = [
    ("order status", {"order_status"}, "Where is my order",
     "Hi, I am Rahul Sharma. Where is my order 1042? I placed it 5 days ago."),
    ("angry refund", {"refund_request", "complaint"}, "Laptop dead",
     "My AeroBook 14 stopped working after 3 days. This is the worst service ever. "
     "Refund me today or I will do a chargeback and tell everyone."),
    ("product question", {"product_inquiry", "pricing_quote"}, "Zenith X1 Pro",
     "Does the Zenith X1 Pro come in a 512 GB version? What is the price?"),
    ("praise", {"feedback"}, "Thanks",
     "Just wanted to say my SoundBud Air earbuds are great. Thank you team!"),
    ("mild complaint", {"complaint"}, "Late delivery",
     "My delivery came two days late and the box was dented. Please note this."),
    ("spam", {"spam"}, "You won",
     "CONGRATULATIONS!!! You won 1,000,000 dollars. Click http://bit.ly/free-prize now to claim your free iPhone."),
]

for label, allowed, subject, message in CASES:
    redacted, _ = redact(message, name=NAME, email=EMAIL)
    state = new_state(0)
    state.update(selected_category="other", subject=subject, redacted_message=redacted)
    analysis = get_or_run_analysis(state)
    u, r = analysis.split()
    ok = "OK   " if u.category in allowed else "CHECK"
    print(
        f"{ok} {label:16} category={u.category:16} spam={u.is_spam!s:5} "
        f"urgency={r.urgency_score} sentiment={r.sentiment:8} loss={r.loss_risk:6} "
        f"escalate={r.escalate!s:5} calls={state['llm_calls']}"
    )
    time.sleep(4)  # stay far below 15 requests per minute