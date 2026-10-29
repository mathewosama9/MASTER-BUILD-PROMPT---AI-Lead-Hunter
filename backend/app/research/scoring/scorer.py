"""Deterministic, explainable lead scoring (0-100).

The score is computed purely from normalized attributes. AI output contributes *evidence-backed* inputs
(fit estimates, recommended services) but cannot set the score directly. Weights are configurable per
workspace; every stored score records its weights and `SCORING_VERSION`.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models.enums import Priority

SCORING_VERSION = "1.1.0"

DEFAULT_WEIGHTS: dict[str, float] = {
    "industry_fit": 0.25,
    "service_relevance": 0.25,
    "contact_availability": 0.20,
    "evidence_strength": 0.15,
    "characteristics_fit": 0.10,
    "data_freshness": 0.05,
}

DEFAULT_THRESHOLDS = {"high": 70.0, "medium": 50.0, "min_evidence": 0.25}


@dataclass
class ContactSummary:
    verified_direct: int = 0  # verified email or phone
    discovered_role_email: int = 0
    discovered_phone_or_whatsapp: int = 0
    indirect_only: int = 0  # contact page / social only


@dataclass
class ScoringInput:
    industry_matches_target: bool
    ai_industry_fit: float | None
    recommended_services: list[str]
    wanted_services: list[str]
    contacts: ContactSummary
    observed_signal_count: int
    pages_inspected: int
    assessment_confidence: float | None
    characteristics_fit: float | None
    has_target_characteristics: bool
    last_enriched_at: datetime | None
    website_reachable: bool
    # Observations from map listings / public social profiles (rating, followers...). Count as evidence.
    external_observations: int = 0
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ScoreResult:
    total: float
    priority: Priority
    factors: dict[str, float]
    weights: dict[str, float]
    explanation: list[str]
    version: str = SCORING_VERSION


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    merged = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (weights or {}).items() if k in DEFAULT_WEIGHTS}}
    total = sum(max(v, 0.0) for v in merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: max(v, 0.0) / total for k, v in merged.items()}


def score_lead(
    inp: ScoringInput, weights: dict[str, float] | None = None, thresholds: dict[str, float] | None = None
) -> ScoreResult:
    w = normalize_weights(weights)
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    expl: list[str] = []

    # Industry fit
    if inp.ai_industry_fit is not None:
        industry = 0.5 * inp.ai_industry_fit + 0.5 * (1.0 if inp.industry_matches_target else 0.4)
        expl.append(
            f"Industry fit {industry:.2f}: discovery match={inp.industry_matches_target}, "
            f"evidence-based fit={inp.ai_industry_fit:.2f}."
        )
    else:
        industry = 0.7 if inp.industry_matches_target else 0.3
        expl.append(f"Industry fit {industry:.2f}: based on discovery query match only.")

    # Service relevance
    if not inp.recommended_services:
        service = 0.0
        expl.append("Service relevance 0: no evidence-backed service opportunity identified.")
    elif inp.wanted_services:
        overlap = [s for s in inp.recommended_services if s in inp.wanted_services]
        service = 1.0 if overlap and inp.recommended_services[0] in overlap else (0.75 if overlap else 0.35)
        expl.append(
            f"Service relevance {service:.2f}: recommended {inp.recommended_services[:3]} vs offered "
            f"{inp.wanted_services}."
        )
    else:
        service = 0.7
        expl.append("Service relevance 0.70: opportunities identified (no specific services selected).")

    # Contact availability
    c = inp.contacts
    if c.verified_direct:
        contact = 1.0
        expl.append("Contact availability 1.0: verified business email/phone.")
    elif c.discovered_role_email and c.discovered_phone_or_whatsapp:
        contact = 0.8
        expl.append("Contact availability 0.80: published role email and phone (not verified).")
    elif c.discovered_role_email or c.discovered_phone_or_whatsapp:
        contact = 0.6
        expl.append("Contact availability 0.60: a published business channel (not verified).")
    elif c.indirect_only:
        contact = 0.3
        expl.append("Contact availability 0.30: only a contact page or social profile.")
    else:
        contact = 0.0
        expl.append("Contact availability 0: no business contact channel found.")

    # Evidence strength
    sig = min((inp.observed_signal_count + inp.external_observations) / 5.0, 1.0)
    pages = min(inp.pages_inspected / 4.0, 1.0)
    evidence = 0.6 * sig + 0.4 * pages
    if inp.assessment_confidence is not None:
        evidence = 0.6 * evidence + 0.4 * inp.assessment_confidence
    if not inp.website_reachable:
        evidence *= 0.6 if inp.external_observations else 0.3
    expl.append(
        f"Evidence strength {evidence:.2f}: {inp.observed_signal_count} observed website signals across "
        f"{inp.pages_inspected} inspected pages"
        + (f", plus {inp.external_observations} map/social profile observations." if inp.external_observations else ".")
    )

    # Characteristics
    if inp.has_target_characteristics and inp.characteristics_fit is not None:
        chars = inp.characteristics_fit
        expl.append(f"Characteristics fit {chars:.2f}: assessed against requested characteristics.")
    else:
        chars = 0.5
        expl.append("Characteristics fit 0.50: neutral (no characteristics requested or assessed).")

    # Freshness
    if inp.last_enriched_at is None:
        fresh = 0.0
    else:
        last = inp.last_enriched_at if inp.last_enriched_at.tzinfo else inp.last_enriched_at.replace(tzinfo=UTC)
        age_days = (inp.now - last).days
        fresh = 1.0 if age_days <= 7 else 0.8 if age_days <= 30 else 0.5 if age_days <= 90 else 0.2
    expl.append(f"Data freshness {fresh:.2f}.")

    factors = {
        "industry_fit": round(industry, 4),
        "service_relevance": round(service, 4),
        "contact_availability": round(contact, 4),
        "evidence_strength": round(evidence, 4),
        "characteristics_fit": round(chars, 4),
        "data_freshness": round(fresh, 4),
    }
    total = round(sum(factors[k] * w[k] for k in factors) * 100, 1)

    if evidence < th["min_evidence"] and total >= th["medium"]:
        priority = Priority.NEEDS_REVIEW
        expl.append("Needs review: score is driven by thin evidence.")
    elif total >= th["high"]:
        priority = Priority.HIGH
    elif total >= th["medium"]:
        priority = Priority.MEDIUM
    elif evidence < th["min_evidence"] and inp.website_reachable is False:
        priority = Priority.NEEDS_REVIEW
        expl.append("Needs review: website could not be inspected.")
    else:
        priority = Priority.LOW
    return ScoreResult(
        total=total,
        priority=priority,
        factors=factors,
        weights={k: round(v, 4) for k, v in w.items()},
        explanation=expl,
    )
