"""Structured AI outputs. Kept free of numeric/length constraints the structured-output API may not support;
range checks happen in `validate_grounding`."""

from typing import Literal

from pydantic import BaseModel, Field

ServiceKey = Literal[
    "ai_support_agent",
    "whatsapp_automation",
    "n8n_automation",
    "crm_integration",
    "appointment_automation",
    "website_development",
    "ecommerce_development",
    "lead_management",
    "ai_sales_assistant",
    "process_automation",
]


class ObservedSignal(BaseModel):
    signal: str = Field(description="What was directly observed, e.g. 'The website has a contact form'.")
    evidence_ids: list[str] = Field(description="IDs (E1, E2...) of the evidence items that show it.")


class Hypothesis(BaseModel):
    statement: str = Field(description="A reasonable but unverified inference. Phrase as uncertain.")
    basis_evidence_ids: list[str]
    confidence: Literal["low", "medium", "high"]


class ServiceRecommendation(BaseModel):
    service: ServiceKey
    rationale: str
    evidence_ids: list[str]


class BusinessAnalysis(BaseModel):
    business_summary: str = Field(description="2-3 sentences, only facts present in the evidence.")
    observed_signals: list[ObservedSignal]
    hypotheses: list[Hypothesis]
    potential_problems: list[str] = Field(description="Possible pain points, phrased as possibilities.")
    recommended_services: list[ServiceRecommendation] = Field(description="Most relevant first; at most 3.")
    opportunity: str = Field(description="Why this could be a business opportunity, referencing evidence.")
    suggested_pitch: str = Field(
        description="A short, specific, human opening line. No guarantees or fake familiarity."
    )
    unknowns: list[str] = Field(description="What could not be verified and needs manual review.")
    confidence: float = Field(description="0.0-1.0 confidence in this assessment given the evidence available.")
    industry_fit: float = Field(description="0.0-1.0: how well the business matches the target industry.")
    characteristics_fit: float = Field(description="0.0-1.0: match with the desired business characteristics.")


class ResearchSpec(BaseModel):
    industry: str = Field(
        description="Best matching industry key from the provided list, or a short free-text industry."
    )
    country: str | None = Field(description="ISO 3166-1 alpha-2 country code if stated.")
    city: str | None
    keywords: list[str] = Field(description="Search keywords in the language(s) of the market (English and Arabic).")
    excluded_keywords: list[str]
    characteristics: list[str] = Field(description="Desired business characteristics mentioned by the user.")
    services: list[ServiceKey] = Field(description="Services the user wants to sell, if implied.")
    language: Literal["en", "ar"]


class PitchDraft(BaseModel):
    short_intro: str
    email_subject: str
    email_body: str
    whatsapp_message: str
    follow_up: str
    proposal_summary: str
