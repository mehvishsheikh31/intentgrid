import importlib.util
from pathlib import Path

from sqlalchemy import func, select

from app.models import Policy
from repositories.policies import get_policy, upsert_policy

_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_policies.py"
_spec = importlib.util.spec_from_file_location("seed_policies", _path)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def test_sample_file_parses():
    data = seed.load_sample_policy()
    assert data.business_name == "TechNest"
    for heading in [
        "## Shipping",
        "## Returns and refunds",
        "## Warranty",
        "## Discounts",
        "## Support hours",
        "## Escalation",
    ]:
        assert heading in data.policy_text
    assert "AeroBook 14" in data.policy_text
    assert "{{customer_name}}" in data.tone_guidelines


def test_seed_twice_keeps_one_row(db):
    data = seed.load_sample_policy()
    upsert_policy(db, data)
    upsert_policy(db, data)
    row = get_policy(db)
    assert row.business_name == "TechNest"
    count = db.scalar(
        select(func.count()).select_from(Policy).where(Policy.business_id == 1)
    )
    assert count == 1