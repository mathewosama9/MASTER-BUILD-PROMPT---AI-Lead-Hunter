from app.research.enrichment.dedupe import dedupe_candidates, identity_key
from app.research.enrichment.normalize import business_domain, normalize_domain, normalize_name, normalize_phone
from app.research.providers.base import BusinessCandidate


def cand(name: str, url: str | None = None, phone: str | None = None, src: str = "https://s.example/1"):
    return BusinessCandidate(
        name=name, website_url=url, phone=phone, country="SA", source_provider="test", source_url=src
    )


def test_domain_normalization():
    assert normalize_domain("https://www.Clinic.com.sa/about?x=1") == "clinic.com.sa"
    assert normalize_domain("shop.example.ae") == "example.ae"
    assert normalize_domain("https://bright-dental.example") == "bright-dental.example"
    assert normalize_domain("") is None


def test_shared_hosts_are_not_identity_keys():
    assert business_domain("https://www.facebook.com/someclinic") is None
    assert business_domain("https://instagram.com/x") is None
    assert business_domain("https://smileclinic.sa") == "smileclinic.sa"


def test_arabic_name_normalization():
    assert normalize_name("شركة النُّور للتجارة") == normalize_name("النور")
    assert normalize_name("Smile Dental LLC") == "smile dental"


def test_phone_normalization():
    assert normalize_phone("011 555 0100", "SA") is None or normalize_phone("011 555 0100", "SA").startswith("+966")
    assert normalize_phone("+971 4 555 0101", None) == "+97145550101"
    assert normalize_phone("12", "SA") is None


def test_in_batch_dedupe_by_domain():
    groups, removed = dedupe_candidates(
        [
            cand("Smile Dental", "https://smile.sa"),
            cand("Smile Dental Clinic - Riyadh", "https://www.smile.sa/contact", src="https://s.example/2"),
            cand("Other", "https://other.sa"),
        ]
    )
    assert removed == 1
    assert len(groups) == 2
    assert len(groups[0].all) == 2


def test_same_name_different_business_is_not_merged():
    groups, removed = dedupe_candidates(
        [
            cand("Smile Dental", "https://smile-riyadh.sa"),
            cand("Smile Dental", "https://smile-jeddah.sa"),
            cand("Smile Dental"),  # no identifiers
            cand("Smile Dental"),  # no identifiers either: must not merge by name
        ]
    )
    assert removed == 0
    assert len(groups) == 4


def test_phone_used_when_no_domain():
    a = cand("A", phone="+971 4 555 0101")
    assert identity_key(a) == "phone:+97145550101"
    groups, removed = dedupe_candidates([a, cand("A branch", phone="+97145550101")])
    assert removed == 1
