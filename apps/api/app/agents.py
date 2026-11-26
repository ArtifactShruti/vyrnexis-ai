from pydantic import BaseModel


class AgentOutput(BaseModel):
    agent: str
    finding: str
    evidence: list[str]
    confidence: float | None
    confidence_note: str | None = None
    alternatives: list[str]
    recommended_action: str
    requires_approval: bool


AGENT_DEFINITIONS = {
    "ORACLE": "Predictive analytics, anomaly forecasting, and organizational intelligence.",
    "SENTINEL": "Defensive monitoring, suspicious-event detection, and posture analysis.",
    "TRACE": "Authorized forensic correlation and timeline reconstruction.",
    "AEGIS": "Risk evaluation, compliance monitoring, and policy enforcement.",
    "MERCURY": "E-commerce transaction anomalies and fraud detection.",
    "NEXUS": "Agent orchestration and workflow communication.",
    "VERITAS": "Evidence validation and unsupported-conclusion detection.",
}
