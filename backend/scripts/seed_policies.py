import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.schemas import PolicyIn  # noqa: E402
from repositories.policies import get_policy, upsert_policy  # noqa: E402

SAMPLE_FILE = Path(__file__).resolve().parents[1] / "data" / "sample_policy.md"
SECTIONS = ("BUSINESS_NAME", "POLICY_TEXT", "TONE_GUIDELINES")


def load_sample_policy(path: Path = SAMPLE_FILE) -> PolicyIn:
    """Read sample_policy.md and split it on the === NAME === marker lines."""
    text = path.read_text(encoding="utf-8-sig")
    parts: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        marker = line.strip()
        if marker.startswith("=== ") and marker.endswith(" ==="):
            current = marker[4:-4].strip()
            parts[current] = []
        elif current is not None:
            parts[current].append(line)

    missing = [s for s in SECTIONS if s not in parts]
    if missing:
        raise ValueError(f"sample_policy.md is missing sections: {missing}")

    return PolicyIn(
        business_name="\n".join(parts["BUSINESS_NAME"]).strip(),
        policy_text="\n".join(parts["POLICY_TEXT"]).strip(),
        tone_guidelines="\n".join(parts["TONE_GUIDELINES"]).strip(),
    )


def main() -> None:
    data = load_sample_policy()
    db = SessionLocal()
    try:
        upsert_policy(db, data)
        row = get_policy(db)
        print(f"Policy saved: id={row.id}, business={row.business_name}")
        print(f"policy_text: {len(row.policy_text)} characters")
        print(f"tone_guidelines: {len(row.tone_guidelines)} characters")
    finally:
        db.close()


if __name__ == "__main__":
    main()