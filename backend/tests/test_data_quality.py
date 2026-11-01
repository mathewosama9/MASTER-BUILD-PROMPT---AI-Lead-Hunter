"""Business-level data quality: relevance gate, dedupe across keys, local phones, junk emails, directory lines."""

from app.research.enrichment.contacts import extract_contacts, find_phones, is_junk_email
from app.research.enrichment.dedupe import dedupe_candidates
from app.research.enrichment.relevance import is_closed, judge_industry, listing_points
from app.research.providers.base import BusinessCandidate
from app.research.providers.directories import drop_directory_lines
from app.research.scraping.parsers import parse_maps_place


def cand(name, url=None, phone=None, src="https://s.example/1", **raw):
    return BusinessCandidate(
        name=name, website_url=url, phone=phone, country="SA", source_provider="test", source_url=src, raw=raw
    )


# ------------------------------------------------------------------------------------------------- dedupe


def test_a_phone_only_listing_joins_the_record_found_through_its_website():
    groups, removed = dedupe_candidates(
        [cand("Smile Dental", "https://smile.sa", "+966 11 444 5566"), cand("Smile Dental Clinic", phone="0114445566")]
    )
    assert removed == 1 and len(groups) == 1
    assert groups[0].key == "domain:smile.sa" and groups[0].phone == "+966114445566"


def test_two_websites_sharing_a_phone_stay_two_businesses():
    groups, removed = dedupe_candidates(
        [cand("Branch A", "https://a.sa", "+966114445566"), cand("Branch B", "https://b.sa", "+966114445566")]
    )
    assert removed == 0 and len(groups) == 2


def test_the_website_is_taken_from_any_listing_of_the_group():
    groups, _ = dedupe_candidates(
        [cand("Smile", phone="+966114445566"), cand("Smile", "https://smile.sa/x", "011 444 5566")]
    )
    assert groups[0].website_url == "https://smile.sa/x" and groups[0].key == "domain:smile.sa"


# ------------------------------------------------------------------------------------------------- phones


def test_local_numbers_are_read_for_the_campaign_country():
    text = "Call us 050 123 4567 or 011 444 5566. CR 1010123456. Order #20231115"
    found = find_phones(text, "SA")
    assert "050 123 4567" in found and "011 444 5566" in found
    assert not any("1010123456" in f or "20231115" in f for f in found)
    assert find_phones(text, None) == []  # no market: only international numbers are trusted


def test_page_text_local_numbers_become_contacts():
    html = "<html><body><p>واتساب 0501234567</p></body></html>"
    values = {c.normalized_value for c in extract_contacts(html, "https://x.sa", "SA", "x.sa").contacts}
    assert "+966501234567" in values


# ------------------------------------------------------------------------------------------------- emails


def test_placeholder_and_tracker_emails_are_junk():
    for junk in (
        "your@email.com",
        "name@company.com",
        "logo@2x.png",
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6@sentry.wixpress.com",
        "x@mailinator.com",
        "info@example.org",
    ):
        assert is_junk_email(junk), junk
    assert not is_junk_email("omar@smile-dental.sa") and not is_junk_email("info@smile-dental.sa")


# ------------------------------------------------------------------------------------------------ directories


def test_a_number_shown_for_many_listings_is_the_directorys_own():
    a = cand("Smile Dental", phone="+20 2 1234 5678", src="https://dir.eg/a")
    b = cand("Nile Clinic", phone="+20 2 1234 5678", src="https://dir.eg/b")
    c = cand("Cairo Smiles", phone="+20 10 1111 2222", src="https://dir.eg/c")
    out = drop_directory_lines([a, b, c])
    assert [x.phone for x in out] == [None, None, "+20 10 1111 2222"]


# ------------------------------------------------------------------------------------------- relevance gate


def test_closed_places_and_listing_points():
    assert is_closed([cand("A", closed="permanent")]) and not is_closed([cand("B", closed="temporary")])
    assert listing_points([cand("C", lat=24.75, lng=46.70), cand("D")]) == [(24.75, 46.70, "test")]


def test_maps_listing_says_when_a_place_is_closed():
    html = '<html><body><div role="main"><h1>Smile</h1><span>Permanently closed</span></div></body></html>'
    assert parse_maps_place(html, "https://www.google.com/maps/place/x").closed == "permanent"
    assert parse_maps_place("<html><body><h1>Smile</h1></body></html>", "u").closed is None


class _FakeAI:
    provider = "deepseek"

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.prompts: list[str] = []

    async def structured(self, system, user, schema):
        from app.research.analysis.ai_service import AIResult

        self.prompts.append(user)
        items = [{"i": i, "verdict": v} for i, v in self.verdicts.items()]
        return AIResult(schema(items=items), "deepseek", "m", 10, 10, 0.002)


async def test_only_clear_mismatches_are_dropped_by_the_ai():
    groups = [[cand("Smile Dental")], [cand("Al Dawaa Pharmacy")], [cand("Noor Center")]]
    ai = _FakeAI({0: "match", 1: "mismatch", 2: "unsure", 7: "mismatch"})  # 7 is not a candidate: ignored
    verdicts, cost = await judge_industry(ai, groups, "Dental Clinics", ["dentist", "عيادة أسنان"], "Riyadh")
    assert verdicts == {0: "match", 1: "mismatch", 2: "unsure"} and cost == 0.002
    assert "<candidates>" in ai.prompts[0] and "Dental Clinics" in ai.prompts[0]
