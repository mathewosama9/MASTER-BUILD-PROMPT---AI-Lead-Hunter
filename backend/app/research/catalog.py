"""Reference data: markets, industries and services in English and Arabic.

Countries are data, not code: add an entry here (or via workspace settings) to support a new market.
"""

from typing import TypedDict


class Country(TypedDict):
    code: str
    name_en: str
    name_ar: str
    cities: list[tuple[str, str]]  # (en, ar)
    search_lang: str
    brave_country: str  # Brave Search country param; "ALL" when not supported


COUNTRIES: dict[str, Country] = {
    "SA": {
        "code": "SA",
        "name_en": "Saudi Arabia",
        "name_ar": "السعودية",
        "search_lang": "ar",
        "brave_country": "SA",
        "cities": [
            ("Riyadh", "الرياض"),
            ("Jeddah", "جدة"),
            ("Dammam", "الدمام"),
            ("Mecca", "مكة"),
            ("Medina", "المدينة المنورة"),
            ("Khobar", "الخبر"),
            ("Abha", "أبها"),
            ("Tabuk", "تبوك"),
        ],
    },
    "AE": {
        "code": "AE",
        "name_en": "United Arab Emirates",
        "name_ar": "الإمارات",
        "search_lang": "en",
        "brave_country": "ALL",
        "cities": [
            ("Dubai", "دبي"),
            ("Abu Dhabi", "أبوظبي"),
            ("Sharjah", "الشارقة"),
            ("Ajman", "عجمان"),
            ("Ras Al Khaimah", "رأس الخيمة"),
            ("Al Ain", "العين"),
        ],
    },
    "EG": {
        "code": "EG",
        "name_en": "Egypt",
        "name_ar": "مصر",
        "search_lang": "ar",
        "brave_country": "ALL",
        "cities": [
            ("Cairo", "القاهرة"),
            ("Giza", "الجيزة"),
            ("Alexandria", "الإسكندرية"),
            ("New Cairo", "القاهرة الجديدة"),
            ("6th of October", "السادس من أكتوبر"),
            ("Mansoura", "المنصورة"),
        ],
    },
}


class Industry(TypedDict):
    key: str
    en: str
    ar: str
    terms_en: list[str]
    terms_ar: list[str]


INDUSTRIES: dict[str, Industry] = {
    i["key"]: i
    for i in [
        {
            "key": "medical_clinics",
            "en": "Medical Clinics",
            "ar": "العيادات الطبية",
            "terms_en": ["medical clinic", "polyclinic", "medical center"],
            "terms_ar": ["عيادة", "مجمع طبي", "مركز طبي"],
        },
        {
            "key": "dental_clinics",
            "en": "Dental Clinics",
            "ar": "عيادات الأسنان",
            "terms_en": ["dental clinic", "dentist", "orthodontics"],
            "terms_ar": ["عيادة أسنان", "طبيب أسنان", "تقويم أسنان"],
        },
        {
            "key": "real_estate",
            "en": "Real Estate",
            "ar": "العقارات",
            "terms_en": ["real estate agency", "property developer", "real estate brokerage"],
            "terms_ar": ["مكتب عقاري", "شركة تطوير عقاري", "وساطة عقارية"],
        },
        {
            "key": "ecommerce",
            "en": "E-commerce",
            "ar": "التجارة الإلكترونية",
            "terms_en": ["online store", "e-commerce shop"],
            "terms_ar": ["متجر إلكتروني", "متجر أونلاين"],
        },
        {
            "key": "restaurants",
            "en": "Restaurants",
            "ar": "المطاعم",
            "terms_en": ["restaurant", "cafe", "catering"],
            "terms_ar": ["مطعم", "مقهى", "تموين"],
        },
        {
            "key": "education",
            "en": "Education",
            "ar": "التعليم",
            "terms_en": ["training center", "private school", "language institute"],
            "terms_ar": ["مركز تدريب", "مدرسة خاصة", "معهد لغات"],
        },
        {
            "key": "beauty_salons",
            "en": "Beauty & Spa",
            "ar": "التجميل والسبا",
            "terms_en": ["beauty salon", "spa", "aesthetic clinic"],
            "terms_ar": ["صالون تجميل", "سبا", "عيادة تجميل"],
        },
        {
            "key": "fitness",
            "en": "Gyms & Fitness",
            "ar": "النوادي الرياضية",
            "terms_en": ["gym", "fitness center"],
            "terms_ar": ["نادي رياضي", "مركز لياقة"],
        },
        {
            "key": "legal",
            "en": "Law Firms",
            "ar": "مكاتب المحاماة",
            "terms_en": ["law firm", "legal consultancy"],
            "terms_ar": ["مكتب محاماة", "استشارات قانونية"],
        },
        {
            "key": "automotive",
            "en": "Automotive",
            "ar": "السيارات",
            "terms_en": ["car dealership", "car service center"],
            "terms_ar": ["معرض سيارات", "مركز صيانة سيارات"],
        },
        {
            "key": "logistics",
            "en": "Logistics",
            "ar": "الخدمات اللوجستية",
            "terms_en": ["logistics company", "freight forwarding"],
            "terms_ar": ["شركة شحن", "خدمات لوجستية"],
        },
        {
            "key": "hospitality",
            "en": "Hotels & Hospitality",
            "ar": "الفنادق والضيافة",
            "terms_en": ["hotel", "serviced apartments"],
            "terms_ar": ["فندق", "شقق فندقية"],
        },
    ]
}

# OpenStreetMap feature tags per industry: (key, regex of values). Industries missing here (e.g. ecommerce)
# have no physical-map representation and the OSM provider reports them as unsupported.
OSM_TAGS: dict[str, list[tuple[str, str]]] = {
    "medical_clinics": [("amenity", "clinic|doctors|hospital"), ("healthcare", "clinic|doctor|centre")],
    "dental_clinics": [("amenity", "dentist"), ("healthcare", "dentist")],
    "real_estate": [("office", "estate_agent|property_management")],
    "restaurants": [("amenity", "restaurant|cafe|fast_food")],
    "education": [("amenity", "school|college|language_school|training"), ("office", "educational_institution")],
    "beauty_salons": [("shop", "beauty|hairdresser|cosmetics"), ("leisure", "spa"), ("amenity", "spa")],
    "fitness": [("leisure", "fitness_centre|sports_centre")],
    "legal": [("office", "lawyer|notary")],
    "automotive": [("shop", "car|car_repair|car_parts|tyres")],
    "logistics": [("office", "logistics|moving_company|courier"), ("amenity", "post_depot")],
    "hospitality": [("tourism", "hotel|apartment|guest_house|motel")],
}

SERVICES: dict[str, dict[str, str]] = {
    "ai_support_agent": {"en": "AI Customer Support Agent", "ar": "وكيل دعم عملاء بالذكاء الاصطناعي"},
    "whatsapp_automation": {"en": "WhatsApp Automation", "ar": "أتمتة واتساب"},
    "n8n_automation": {"en": "n8n Workflow Automation", "ar": "أتمتة سير العمل عبر n8n"},
    "crm_integration": {"en": "CRM Integration", "ar": "تكامل أنظمة إدارة العملاء"},
    "appointment_automation": {"en": "Appointment Scheduling Automation", "ar": "أتمتة حجز المواعيد"},
    "website_development": {"en": "Website Development", "ar": "تطوير المواقع"},
    "ecommerce_development": {"en": "E-commerce Development", "ar": "تطوير المتاجر الإلكترونية"},
    "lead_management": {"en": "Lead Management Automation", "ar": "أتمتة إدارة العملاء المحتملين"},
    "ai_sales_assistant": {"en": "AI Sales Assistant", "ar": "مساعد مبيعات بالذكاء الاصطناعي"},
    "process_automation": {"en": "Business Process Automation", "ar": "أتمتة العمليات"},
}


def industry_terms(industry: str) -> tuple[list[str], list[str]]:
    """Return (english_terms, arabic_terms) for a catalog key or free-text industry."""
    item = INDUSTRIES.get(industry)
    if item:
        return item["terms_en"], item["terms_ar"]
    return [industry], []


def industry_label(industry: str, lang: str = "en") -> str:
    item = INDUSTRIES.get(industry)
    if not item:
        return industry
    return item["ar"] if lang == "ar" else item["en"]


def city_names(country: str, city: str | None) -> tuple[str | None, str | None]:
    if not city:
        return None, None
    c = COUNTRIES.get(country.upper())
    if c:
        for en, ar in c["cities"]:
            if city.casefold() in (en.casefold(), ar):
                return en, ar
    return city, None


def country_names(country: str) -> tuple[str, str | None]:
    c = COUNTRIES.get(country.upper())
    return (c["name_en"], c["name_ar"]) if c else (country, None)
