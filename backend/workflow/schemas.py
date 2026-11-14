from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Spam is a category here. The contact form never offers it, so only Agent 1 can set it.
AnalysisCategory = Literal[
    "complaint",
    "refund_request",
    "order_status",
    "product_inquiry",
    "pricing_quote",
    "appointment_booking",
    "feedback",
    "spam",
    "other",
]
Sentiment = Literal["positive", "neutral", "negative", "angry"]
LossRisk = Literal["low", "medium", "high"]
Severity = Literal["blocker", "warning"]


class UnderstandingResult(BaseModel):
    """Agent 1 output."""

    category: AnalysisCategory
    intent: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1)
    key_details: list[str] = Field(default_factory=list, max_length=20)
    is_spam: bool = False
    language: str = Field(default="en", max_length=20)
    confidence: float = Field(ge=0, le=1)

    @field_validator("summary")
    @classmethod
    def summary_max_40_words(cls, v: str) -> str:
        if len(v.split()) > 40:
            raise ValueError("summary must be 40 words or fewer")
        return v


class RiskResult(BaseModel):
    """Agent 2 output. priority_score is NOT here: code computes it (step 4.5)."""

    urgency_score: int = Field(ge=1, le=5)
    sentiment: Sentiment
    loss_risk: LossRisk
    risk_reasons: list[str] = Field(default_factory=list, max_length=10)
    escalate: bool = False


class AnalysisResult(BaseModel):
    """What the ONE shared analysis call returns (Agents 1 and 2 together)."""

    understanding: UnderstandingResult
    risk: RiskResult

    def split(self) -> tuple[UnderstandingResult, RiskResult]:
        return self.understanding, self.risk


class DraftResult(BaseModel):
    """Agent 3 output. draft_reply keeps the {{customer_name}} placeholder."""

    draft_reply: str = Field(min_length=1, max_length=4000)
    policies_used: list[str] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)


class ComplianceViolation(BaseModel):
    rule: str = Field(min_length=1)
    severity: Severity
    excerpt: str = ""
    explanation: str = ""


class ComplianceResult(BaseModel):
    """Agent 4 output. It never rewrites the draft and never approves or sends."""

    passed: bool
    violations: list[ComplianceViolation] = Field(default_factory=list)
    revision_feedback: str = ""
    layer: Literal["rules", "llm"] = "rules"