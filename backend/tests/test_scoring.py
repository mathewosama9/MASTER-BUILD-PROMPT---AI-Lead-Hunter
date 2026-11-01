from datetime import UTC, datetime, timedelta

from app.models.enums import Priority
from app.research.scoring.scorer import DEFAULT_WEIGHTS, ContactSummary, ScoringInput, normalize_weights, score_lead


def base(**kw) -> ScoringInput:
    defaults = dict(
        industry_matches_target=True,
        ai_industry_fit=0.9,
        recommended_services=["whatsapp_automation"],
        wanted_services=["whatsapp_automation"],
        contacts=ContactSummary(verified_direct=1),
        observed_signal_count=5,
        pages_inspected=4,
        assessment_confidence=0.8,
        characteristics_fit=None,
        has_target_characteristics=False,
        last_enriched_at=datetime.now(UTC),
        website_reachable=True,
    )
    defaults.update(kw)
    return ScoringInput(**defaults)


def test_score_is_deterministic_and_bounded():
    a = score_lead(base())
    b = score_lead(base())
    assert a.total == b.total
    assert 0 <= a.total <= 100
    assert a.priority == Priority.HIGH
    assert set(a.factors) == set(DEFAULT_WEIGHTS)
    assert a.version and a.explanation


def test_no_contacts_scores_zero_contact_factor():
    r = score_lead(base(contacts=ContactSummary()))
    assert r.factors["contact_availability"] == 0.0
    assert any("no business contact" in e.lower() for e in r.explanation)
    assert r.total < score_lead(base()).total


def test_unverified_contact_scores_lower_than_verified():
    unverified = score_lead(base(contacts=ContactSummary(discovered_role_email=1)))
    verified = score_lead(base())
    assert unverified.factors["contact_availability"] < verified.factors["contact_availability"]


def test_thin_evidence_is_flagged_for_review_not_high():
    r = score_lead(base(observed_signal_count=0, pages_inspected=0, assessment_confidence=0.0, website_reachable=False))
    assert r.priority in (Priority.NEEDS_REVIEW, Priority.LOW)
    assert r.priority != Priority.HIGH


def test_ai_cannot_force_high_score_without_evidence():
    r = score_lead(
        base(
            ai_industry_fit=1.0,
            assessment_confidence=1.0,
            observed_signal_count=0,
            pages_inspected=0,
            website_reachable=False,
            contacts=ContactSummary(),
            recommended_services=[],
        )
    )
    assert r.total < 50


def test_custom_weights_are_normalized_and_recorded():
    w = normalize_weights(
        {
            "industry_fit": 2,
            "service_relevance": 2,
            "contact_availability": 0,
            "evidence_strength": 0,
            "characteristics_fit": 0,
            "data_freshness": 0,
        }
    )
    assert abs(sum(w.values()) - 1.0) < 1e-9
    r = score_lead(base(contacts=ContactSummary()), {"contact_availability": 0})
    assert r.weights["contact_availability"] == 0


def test_freshness_decays():
    old = score_lead(base(last_enriched_at=datetime.now(UTC) - timedelta(days=200)))
    assert old.factors["data_freshness"] == 0.2


def test_a_verified_decision_maker_with_a_direct_channel_is_the_best_contact():
    plain = score_lead(base(contacts=ContactSummary(discovered_phone_or_whatsapp=1)))
    known = score_lead(base(contacts=ContactSummary(discovered_phone_or_whatsapp=1, verified_decision_maker=True)))
    direct = score_lead(base(contacts=ContactSummary(verified_decision_maker=True, decision_maker_direct=True)))
    assert plain.factors["contact_availability"] == 0.6
    assert known.factors["contact_availability"] == 0.7
    assert direct.factors["contact_availability"] == 1.0
