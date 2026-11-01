"""Decision-maker verification and the AI research council (web-searching models)."""

import json

import httpx

from app.research.analysis.web_ai import WebAnswer, ask_council, parse_people, to_candidates
from app.research.enrichment.decision_makers import DecisionMaker
from app.research.enrichment.social_search import SearchHit
from app.research.enrichment.verify_people import (
    BusinessIdentity,
    Proof,
    known_proofs,
    page_proof,
    rule_passes,
    verify_people,
)

BIZ = BusinessIdentity("Smile Dental Clinic", "smile-dental.sa", "Riyadh", "SA", handles=["smiledental"])
ANSWER = json.dumps({"people": [{"name": "Omar Khaled", "role": "Founder", "quote": "q", "source_urls": []}]})

# ------------------------------------------------------------------------------------------ council replies


def _openai(_req):
    msg = {
        "type": "message",
        "content": [
            {
                "type": "output_text",
                "text": f"Here you go:\n```json\n{ANSWER}\n```",
                "annotations": [{"type": "url_citation", "url": "https://press.example/a", "title": "t"}],
            }
        ],
    }
    return httpx.Response(200, json={"output": [{"type": "web_search_call"}, msg], "usage": {"input_tokens": 5}})


def _gemini(_req):
    step = {
        "type": "model_output",
        "content": [
            {"type": "text", "text": ANSWER, "annotations": [{"type": "url_citation", "url": "https://news.example/b"}]}
        ],
    }
    return httpx.Response(200, json={"steps": [{"type": "google_search_call"}, step]})


async def test_each_council_member_is_read_whatever_its_reply_shape():
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openai.com":
            return _openai(request)
        if request.url.host == "generativelanguage.googleapis.com":
            assert request.headers["x-goog-api-key"] == "g"
            return _gemini(request)
        return httpx.Response(401, json={})  # perplexity: bad key

    answers = await ask_council(
        {"perplexity": "p", "gemini": "g", "openai": "o"}, {"name": "Smile"}, transport=httpx.MockTransport(route)
    )
    by = {a.provider: a for a in answers}
    assert by["perplexity"].error and not by["perplexity"].people  # one failing model never blocks the others
    assert [p.name for p in by["openai"].people] == ["Omar Khaled"] and by["openai"].citations == [
        "https://press.example/a"
    ]
    assert by["gemini"].citations == ["https://news.example/b"] and by["gemini"].people[0].role == "Founder"


def test_unusable_replies_name_nobody():
    assert parse_people("I could not find who runs this business.") == []
    assert parse_people('{"people": []}') == []


def test_candidates_keep_only_decision_roles_and_carry_pages_to_check():
    a = WebAnswer(
        "gemini",
        parse_people(
            json.dumps(
                {
                    "people": [
                        {"name": "Omar Khaled", "role": "Owner", "source_urls": ["https://x.example/1"]},
                        {"name": "Mona Ali", "role": "Receptionist", "source_urls": []},
                    ]
                }
            )
        ),
        ["https://search.example/2"],
    )
    found = to_candidates([a])
    assert [d.name for d in found] == ["Omar Khaled"]
    assert found[0].cited_urls == ["https://x.example/1", "https://search.example/2"]
    assert found[0].vouched_by == ["ai:gemini"] and found[0].source == "ai_research"


# ------------------------------------------------------------------------------------------------- proofs

DM = DecisionMaker("Dr. Omar Khaled", "Founder", "ai_research", "", "", 0.5)


def test_a_page_proves_a_person_only_with_this_business():
    ok = page_proof("https://press.example/a", "Dr Omar Khaled founded Smile Dental in Riyadh in 2012.", DM, BIZ)
    assert ok is not None and ok.kind == "third_party"
    namesake = "Omar Khaled, founder of Smile Logistics, spoke at the summit."
    assert page_proof("https://press.example/b", namesake, DM, BIZ) is None
    former = "Former CEO Omar Khaled left Smile Dental last year."
    assert page_proof("https://press.example/c", former, DM, BIZ) is None
    own = page_proof("https://smile-dental.sa/about", "Meet our founder Omar Khaled.", DM, BIZ)
    assert own is not None and own.kind == "first_party" and own.role_stated
    assert page_proof("https://press.example/d", "Smile Dental opened a branch.", DM, BIZ) is None


def test_the_rule_needs_the_business_itself_or_two_different_sites():
    assert rule_passes([Proof("https://smile-dental.sa/team", "first_party", "e", role_stated=True)])
    assert not rule_passes([Proof("https://www.linkedin.com/in/o", "professional", "e", True)])
    assert rule_passes(
        [
            Proof("https://www.linkedin.com/in/o", "professional", "e", True),
            Proof("https://news.sa/x", "third_party", "e"),
        ]
    )
    # two pages of one site are still one source
    assert not rule_passes(
        [Proof("https://news.sa/x", "third_party", "e"), Proof("https://news.sa/y", "third_party", "e")]
    )


def test_proofs_already_in_hand():
    site = DecisionMaker(
        "Omar Khaled", "Founder", "website", "https://smile-dental.sa/team", "Omar Khaled - Founder", 0.6
    )
    assert [p.kind for p in known_proofs(site, BIZ)] == ["first_party"]
    other_site = DecisionMaker("Omar Khaled", "Founder", "website", "https://other.sa/team", "x", 0.6)
    assert known_proofs(other_site, BIZ) == []
    li = DecisionMaker("Omar Khaled", "CEO", "linkedin_search", "https://www.linkedin.com/in/o", "x", 0.55)
    li.proof_hits.append(SearchHit("https://www.linkedin.com/in/o", "Omar Khaled - CEO - Smile Dental | LinkedIn", ""))
    li.vouched_by.append("apollo")
    assert sorted(p.kind for p in known_proofs(li, BIZ)) == ["people_database", "professional"]


# -------------------------------------------------------------------------------------------- the AI judge


class _Judge:
    provider = "deepseek"

    def __init__(self, entries):
        self.entries = entries

    async def structured(self, system, user, schema):
        from app.research.analysis.ai_service import AIResult

        return AIResult(schema(people=self.entries), "deepseek", "m", 10, 10, 0.001)


def _team_person():
    return DecisionMaker(
        "Omar Khaled", "Founder", "website", "https://smile-dental.sa/team", "Omar Khaled - Founder", 0.6
    )


async def test_the_judge_can_turn_down_a_candidate_the_rule_accepted():
    no = {"id": "P1", "same_company": True, "is_current": False, "is_decision_maker": True, "evidence_ids": ["E1"]}
    verified, cost, rejected = await verify_people([_team_person()], BIZ, ai=_Judge([no]))
    assert verified == [] and rejected == 1 and cost == 0.001


async def test_the_judge_must_cite_that_candidates_own_excerpts():
    uncited = {"id": "P1", "same_company": True, "is_current": True, "is_decision_maker": True, "evidence_ids": ["E9"]}
    verified, _, _ = await verify_people([_team_person()], BIZ, ai=_Judge([uncited]))
    assert verified == []
    yes = {**uncited, "evidence_ids": ["E1"], "role": "Founder & CEO", "reason": "named on the team page"}
    verified, _, rejected = await verify_people([_team_person()], BIZ, ai=_Judge([yes]))
    assert rejected == 0 and verified[0][1].role == "Founder & CEO"
    assert verified[0][1].evidence()["proofs"][0]["kind"] == "first_party"


async def test_without_an_ai_the_rule_alone_decides():
    verified, cost, _ = await verify_people([_team_person()], BIZ, ai=None)
    assert len(verified) == 1 and cost == 0.0
