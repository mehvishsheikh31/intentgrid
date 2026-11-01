from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Policy
from app.schemas import PolicyIn


def get_policy(db: Session, business_id: int = 1) -> Policy | None:
    return db.scalar(select(Policy).where(Policy.business_id == business_id))


def upsert_policy(db: Session, data: PolicyIn, business_id: int = 1) -> Policy:
    policy = get_policy(db, business_id)
    if policy is None:
        policy = Policy(business_id=business_id)
        db.add(policy)
    policy.business_name = data.business_name
    policy.policy_text = data.policy_text
    policy.tone_guidelines = data.tone_guidelines
    db.commit()
    db.refresh(policy)
    return policy
