"""Reference data: markets, industries and service-provider categories in English and Arabic.

Countries and industries are data, not code: add an entry here to support a new market or industry. Free-text
industries still work everywhere; the AI search planner (analysis/ai_service.plan_search) fills in their terms.
"""

from typing import NotRequired, TypedDict


class Country(TypedDict):
    code: str
    name_en: str
    name_ar: str
    cities: list[tuple[str, str]]  # (en, ar)
    search_lang: str
    brave_country: str  # Brave Search country param; "ALL" when not supported


def _country(
    code: str, en: str, ar: str, cities: list[tuple[str, str]], lang: str = "ar", brave: str = "ALL"
) -> Country:
    return {"code": code, "name_en": en, "name_ar": ar, "cities": cities, "search_lang": lang, "brave_country": brave}


COUNTRIES: dict[str, Country] = {
    c["code"]: c
    for c in [
        _country(
            "SA",
            "Saudi Arabia",
            "السعودية",
            [
                ("Riyadh", "الرياض"),
                ("Jeddah", "جدة"),
                ("Dammam", "الدمام"),
                ("Mecca", "مكة"),
                ("Medina", "المدينة المنورة"),
                ("Khobar", "الخبر"),
                ("Abha", "أبها"),
                ("Tabuk", "تبوك"),
                ("Taif", "الطائف"),
                ("Buraidah", "بريدة"),
                ("Hail", "حائل"),
                ("Jazan", "جازان"),
                ("Najran", "نجران"),
                ("Al Ahsa", "الأحساء"),
                ("Jubail", "الجبيل"),
                ("Yanbu", "ينبع"),
            ],
            brave="SA",
        ),
        _country(
            "AE",
            "United Arab Emirates",
            "الإمارات",
            [
                ("Dubai", "دبي"),
                ("Abu Dhabi", "أبوظبي"),
                ("Sharjah", "الشارقة"),
                ("Ajman", "عجمان"),
                ("Ras Al Khaimah", "رأس الخيمة"),
                ("Al Ain", "العين"),
                ("Fujairah", "الفجيرة"),
                ("Umm Al Quwain", "أم القيوين"),
            ],
            lang="en",
        ),
        _country(
            "EG",
            "Egypt",
            "مصر",
            [
                ("Cairo", "القاهرة"),
                ("Giza", "الجيزة"),
                ("Alexandria", "الإسكندرية"),
                ("New Cairo", "القاهرة الجديدة"),
                ("6th of October", "السادس من أكتوبر"),
                ("Sheikh Zayed", "الشيخ زايد"),
                ("Mansoura", "المنصورة"),
                ("Tanta", "طنطا"),
                ("Zagazig", "الزقازيق"),
                ("Ismailia", "الإسماعيلية"),
                ("Port Said", "بورسعيد"),
                ("Suez", "السويس"),
                ("Hurghada", "الغردقة"),
                ("Sharm El Sheikh", "شرم الشيخ"),
                ("Asyut", "أسيوط"),
                ("Luxor", "الأقصر"),
                ("Aswan", "أسوان"),
            ],
        ),
        _country(
            "KW",
            "Kuwait",
            "الكويت",
            [
                ("Kuwait City", "مدينة الكويت"),
                ("Hawalli", "حولي"),
                ("Salmiya", "السالمية"),
                ("Farwaniya", "الفروانية"),
                ("Jahra", "الجهراء"),
                ("Ahmadi", "الأحمدي"),
            ],
        ),
        _country(
            "QA",
            "Qatar",
            "قطر",
            [("Doha", "الدوحة"), ("Al Rayyan", "الريان"), ("Al Wakrah", "الوكرة"), ("Lusail", "لوسيل")],
        ),
        _country(
            "BH",
            "Bahrain",
            "البحرين",
            [("Manama", "المنامة"), ("Muharraq", "المحرق"), ("Riffa", "الرفاع"), ("Isa Town", "مدينة عيسى")],
        ),
        _country(
            "OM",
            "Oman",
            "عُمان",
            [("Muscat", "مسقط"), ("Salalah", "صلالة"), ("Sohar", "صحار"), ("Nizwa", "نزوى"), ("Sur", "صور")],
        ),
        _country(
            "JO",
            "Jordan",
            "الأردن",
            [("Amman", "عمّان"), ("Irbid", "إربد"), ("Zarqa", "الزرقاء"), ("Aqaba", "العقبة"), ("Salt", "السلط")],
        ),
        _country(
            "LB",
            "Lebanon",
            "لبنان",
            [("Beirut", "بيروت"), ("Tripoli", "طرابلس"), ("Sidon", "صيدا"), ("Jounieh", "جونيه"), ("Zahle", "زحلة")],
        ),
        _country(
            "IQ",
            "Iraq",
            "العراق",
            [
                ("Baghdad", "بغداد"),
                ("Basra", "البصرة"),
                ("Erbil", "أربيل"),
                ("Mosul", "الموصل"),
                ("Najaf", "النجف"),
                ("Karbala", "كربلاء"),
                ("Sulaymaniyah", "السليمانية"),
            ],
        ),
        _country(
            "MA",
            "Morocco",
            "المغرب",
            [
                ("Casablanca", "الدار البيضاء"),
                ("Rabat", "الرباط"),
                ("Marrakesh", "مراكش"),
                ("Fes", "فاس"),
                ("Tangier", "طنجة"),
                ("Agadir", "أكادير"),
                ("Meknes", "مكناس"),
            ],
        ),
        _country(
            "DZ",
            "Algeria",
            "الجزائر",
            [
                ("Algiers", "الجزائر العاصمة"),
                ("Oran", "وهران"),
                ("Constantine", "قسنطينة"),
                ("Annaba", "عنابة"),
                ("Setif", "سطيف"),
            ],
        ),
        _country(
            "TN",
            "Tunisia",
            "تونس",
            [
                ("Tunis", "تونس العاصمة"),
                ("Sfax", "صفاقس"),
                ("Sousse", "سوسة"),
                ("Nabeul", "نابل"),
                ("Bizerte", "بنزرت"),
            ],
        ),
        _country(
            "LY",
            "Libya",
            "ليبيا",
            [("Tripoli", "طرابلس"), ("Benghazi", "بنغازي"), ("Misrata", "مصراتة")],
        ),
        _country(
            "SD",
            "Sudan",
            "السودان",
            [("Khartoum", "الخرطوم"), ("Omdurman", "أم درمان"), ("Port Sudan", "بورتسودان")],
        ),
        _country(
            "PS",
            "Palestine",
            "فلسطين",
            [("Ramallah", "رام الله"), ("Nablus", "نابلس"), ("Hebron", "الخليل"), ("Bethlehem", "بيت لحم")],
        ),
    ]
}


class Industry(TypedDict):
    key: str
    group: str
    en: str
    ar: str
    terms_en: list[str]
    terms_ar: list[str]
    osm: NotRequired[list[tuple[str, str]]]


INDUSTRY_GROUPS: dict[str, dict[str, str]] = {
    "health": {"en": "Healthcare", "ar": "الصحة والطب"},
    "food": {"en": "Food & Beverage", "ar": "الأكل والمشروبات"},
    "retail": {"en": "Retail & Shops", "ar": "التجزئة والمحلات"},
    "professional": {"en": "Professional Services", "ar": "الخدمات المهنية"},
    "property": {"en": "Real Estate & Construction", "ar": "العقارات والمقاولات"},
    "education": {"en": "Education & Training", "ar": "التعليم والتدريب"},
    "beauty_fitness": {"en": "Beauty & Fitness", "ar": "التجميل واللياقة"},
    "auto": {"en": "Automotive", "ar": "السيارات"},
    "industrial": {"en": "Industry & Supply", "ar": "الصناعة والتوريدات"},
    "logistics": {"en": "Logistics & Transport", "ar": "اللوجستيات والنقل"},
    "travel": {"en": "Hospitality & Travel", "ar": "الضيافة والسياحة"},
    "tech_media": {"en": "Tech & Media", "ar": "التقنية والإعلام"},
    "events": {"en": "Events & Weddings", "ar": "المناسبات والأفراح"},
    "home_services": {"en": "Home & Facility Services", "ar": "الخدمات المنزلية والصيانة"},
    "agriculture": {"en": "Agriculture", "ar": "الزراعة"},
    "community": {"en": "Organisations & Workspaces", "ar": "الجمعيات ومساحات العمل"},
}


def _ind(
    key: str,
    group: str,
    en: str,
    ar: str,
    terms_en: list[str],
    terms_ar: list[str],
    osm: list[tuple[str, str]] | None = None,
) -> Industry:
    item: Industry = {"key": key, "group": group, "en": en, "ar": ar, "terms_en": terms_en, "terms_ar": terms_ar}
    if osm:
        item["osm"] = osm
    return item


# OSM tags are (key, regex of values). Industries without them have no reliable map representation and the OSM
# provider reports them as unsupported.
INDUSTRIES: dict[str, Industry] = {
    i["key"]: i
    for i in [
        # Healthcare
        _ind(
            "medical_clinics",
            "health",
            "Medical Clinics",
            "العيادات الطبية",
            ["medical clinic", "polyclinic", "medical center"],
            ["عيادة", "مجمع طبي", "مركز طبي"],
            [("amenity", "clinic|doctors|hospital"), ("healthcare", "clinic|doctor|centre")],
        ),
        _ind(
            "dental_clinics",
            "health",
            "Dental Clinics",
            "عيادات الأسنان",
            ["dental clinic", "dentist", "orthodontics"],
            ["عيادة أسنان", "طبيب أسنان", "تقويم أسنان"],
            [("amenity", "dentist"), ("healthcare", "dentist")],
        ),
        _ind(
            "hospitals",
            "health",
            "Hospitals",
            "المستشفيات",
            ["hospital", "private hospital"],
            ["مستشفى", "مستشفى خاص"],
            [("amenity", "hospital"), ("healthcare", "hospital")],
        ),
        _ind(
            "pharmacies",
            "health",
            "Pharmacies",
            "الصيدليات",
            ["pharmacy", "drugstore"],
            ["صيدلية"],
            [("amenity", "pharmacy"), ("healthcare", "pharmacy")],
        ),
        _ind(
            "laboratories",
            "health",
            "Labs & Radiology",
            "معامل التحاليل والأشعة",
            ["medical laboratory", "diagnostic center", "radiology center"],
            ["معمل تحاليل", "مختبر طبي", "مركز أشعة"],
            [("healthcare", "laboratory|diagnostics")],
        ),
        _ind(
            "physiotherapy",
            "health",
            "Physiotherapy",
            "العلاج الطبيعي",
            ["physiotherapy center", "physical therapy clinic"],
            ["مركز علاج طبيعي", "عيادة علاج طبيعي"],
            [("healthcare", "physiotherapist")],
        ),
        _ind(
            "optics",
            "health",
            "Opticians & Eye Clinics",
            "النظارات وعيادات العيون",
            ["optician", "eye clinic"],
            ["محل نظارات", "بصريات", "عيادة عيون"],
            [("shop", "optician"), ("healthcare", "optometrist")],
        ),
        _ind(
            "psychology",
            "health",
            "Mental Health Clinics",
            "عيادات الصحة النفسية",
            ["psychologist", "counseling center"],
            ["عيادة نفسية", "مركز استشارات نفسية"],
            [("healthcare", "psychotherapist")],
        ),
        _ind(
            "veterinary",
            "health",
            "Veterinary & Pets",
            "العيادات البيطرية والحيوانات الأليفة",
            ["veterinary clinic", "pet shop", "pet grooming"],
            ["عيادة بيطرية", "محل حيوانات أليفة", "تجميل حيوانات"],
            [("amenity", "veterinary"), ("shop", "pet|pet_grooming")],
        ),
        # Food & beverage
        _ind(
            "restaurants",
            "food",
            "Restaurants",
            "المطاعم",
            ["restaurant", "cafe", "catering"],
            ["مطعم", "مقهى", "تموين"],
            [("amenity", "restaurant|cafe|fast_food")],
        ),
        _ind(
            "cafes",
            "food",
            "Cafés & Coffee Shops",
            "الكافيهات",
            ["coffee shop", "specialty coffee", "cafe"],
            ["كافيه", "كوفي شوب", "مقهى"],
            [("amenity", "cafe")],
        ),
        _ind(
            "bakeries",
            "food",
            "Bakeries & Sweets",
            "المخابز والحلويات",
            ["bakery", "pastry shop", "sweets shop"],
            ["مخبز", "حلويات", "محل حلويات"],
            [("shop", "bakery|pastry|confectionery")],
        ),
        _ind(
            "catering",
            "food",
            "Catering & Cloud Kitchens",
            "التموين والمطابخ السحابية",
            ["catering company", "cloud kitchen"],
            ["شركة تموين", "مطبخ سحابي", "تجهيز ولائم"],
        ),
        _ind(
            "food_supply",
            "food",
            "Food Suppliers",
            "موردو المواد الغذائية",
            ["food supplier", "food distributor"],
            ["مورد مواد غذائية", "توزيع أغذية"],
            [("shop", "wholesale")],
        ),
        # Retail
        _ind(
            "ecommerce",
            "retail",
            "E-commerce",
            "التجارة الإلكترونية",
            ["online store", "e-commerce shop"],
            ["متجر إلكتروني", "متجر أونلاين"],
        ),
        _ind(
            "supermarkets",
            "retail",
            "Supermarkets & Groceries",
            "السوبر ماركت والبقالات",
            ["supermarket", "grocery store", "hypermarket"],
            ["سوبر ماركت", "بقالة", "هايبر ماركت"],
            [("shop", "supermarket|convenience|greengrocer")],
        ),
        _ind(
            "fashion",
            "retail",
            "Fashion & Clothing",
            "الملابس والأزياء",
            ["clothing store", "boutique", "abaya shop", "shoe store"],
            ["محل ملابس", "بوتيك", "محل عبايات", "محل أحذية"],
            [("shop", "clothes|boutique|shoes|fashion")],
        ),
        _ind(
            "electronics",
            "retail",
            "Electronics & Mobiles",
            "الإلكترونيات والجوالات",
            ["electronics store", "mobile phone shop", "computer store"],
            ["محل إلكترونيات", "محل جوالات", "محل موبايلات"],
            [("shop", "electronics|mobile_phone|computer")],
        ),
        _ind(
            "furniture",
            "retail",
            "Furniture & Home Decor",
            "الأثاث والديكور",
            ["furniture store", "home decor store", "curtains shop"],
            ["معرض أثاث", "ديكور منزلي", "مفروشات", "محل ستائر"],
            [("shop", "furniture|interior_decoration|bed|curtain")],
        ),
        _ind(
            "jewelry",
            "retail",
            "Jewelry & Gold",
            "المجوهرات والذهب",
            ["jewelry store", "gold shop"],
            ["محل مجوهرات", "محل ذهب"],
            [("shop", "jewelry")],
        ),
        _ind(
            "perfumes",
            "retail",
            "Perfumes & Cosmetics",
            "العطور ومستحضرات التجميل",
            ["perfume shop", "oud shop", "cosmetics store"],
            ["محل عطور", "محل عود", "مستحضرات تجميل"],
            [("shop", "perfumery|cosmetics")],
        ),
        _ind(
            "flowers_gifts",
            "retail",
            "Flowers & Gifts",
            "الورد والهدايا",
            ["flower shop", "gift shop"],
            ["محل ورد", "محل هدايا"],
            [("shop", "florist|gift")],
        ),
        _ind(
            "bookstores",
            "retail",
            "Bookstores & Stationery",
            "المكتبات والأدوات المكتبية",
            ["bookstore", "stationery store"],
            ["مكتبة", "أدوات مكتبية"],
            [("shop", "books|stationery")],
        ),
        # Professional services
        _ind(
            "legal",
            "professional",
            "Law Firms",
            "مكاتب المحاماة",
            ["law firm", "legal consultancy"],
            ["مكتب محاماة", "استشارات قانونية"],
            [("office", "lawyer|notary")],
        ),
        _ind(
            "accounting",
            "professional",
            "Accounting & Audit",
            "المحاسبة والمراجعة",
            ["accounting firm", "audit firm", "tax consultant"],
            ["مكتب محاسبة", "مكتب مراجعة حسابات", "مستشار ضرائب"],
            [("office", "accountant|tax_advisor")],
        ),
        _ind(
            "consulting",
            "professional",
            "Business Consulting",
            "الاستشارات الإدارية",
            ["business consultancy", "management consulting"],
            ["شركة استشارات", "استشارات إدارية"],
            [("office", "consulting")],
        ),
        _ind(
            "insurance",
            "professional",
            "Insurance",
            "التأمين",
            ["insurance company", "insurance broker"],
            ["شركة تأمين", "وسيط تأمين"],
            [("office", "insurance")],
        ),
        _ind(
            "finance",
            "professional",
            "Finance & Exchange",
            "التمويل والصرافة",
            ["finance company", "exchange office"],
            ["شركة تمويل", "صرافة"],
            [("office", "financial|financial_advisor"), ("amenity", "bureau_de_change")],
        ),
        _ind(
            "marketing_agencies",
            "professional",
            "Marketing & Advertising Agencies",
            "وكالات التسويق والإعلان",
            ["marketing agency", "advertising agency", "digital marketing agency"],
            ["وكالة تسويق", "وكالة إعلان", "شركة تسويق رقمي"],
            [("office", "advertising_agency")],
        ),
        _ind(
            "recruitment",
            "professional",
            "Recruitment & Manpower",
            "التوظيف والاستقدام",
            ["recruitment agency", "manpower company"],
            ["مكتب توظيف", "شركة استقدام", "مكتب استقدام"],
            [("office", "employment_agency")],
        ),
        _ind(
            "translation",
            "professional",
            "Translation Offices",
            "مكاتب الترجمة",
            ["translation office", "certified translation"],
            ["مكتب ترجمة", "ترجمة معتمدة"],
            [("office", "translator")],
        ),
        _ind(
            "engineering",
            "professional",
            "Engineering & Architecture",
            "المكاتب الهندسية",
            ["architecture firm", "engineering consultancy"],
            ["مكتب هندسي", "مكتب استشارات هندسية", "مكتب معماري"],
            [("office", "architect|engineer")],
        ),
        # Real estate & construction
        _ind(
            "real_estate",
            "property",
            "Real Estate",
            "العقارات",
            ["real estate agency", "property developer", "real estate brokerage"],
            ["مكتب عقاري", "شركة تطوير عقاري", "وساطة عقارية"],
            [("office", "estate_agent|property_management")],
        ),
        _ind(
            "construction",
            "property",
            "Construction & Contracting",
            "المقاولات",
            ["construction company", "contractor"],
            ["شركة مقاولات", "مقاول"],
            [("office", "construction_company"), ("craft", "builder")],
        ),
        _ind(
            "interior_design",
            "property",
            "Interior Design & Finishing",
            "التصميم الداخلي والتشطيبات",
            ["interior design company", "finishing company"],
            ["شركة تصميم داخلي", "شركة تشطيبات", "ديكور"],
            [("shop", "interior_decoration")],
        ),
        _ind(
            "building_materials",
            "property",
            "Building Materials",
            "مواد البناء",
            ["building materials supplier", "hardware store", "ceramic showroom"],
            ["مواد بناء", "أدوات صحية", "معرض سيراميك"],
            [("shop", "hardware|doityourself|trade|tiles|bathroom_furnishing")],
        ),
        # Education
        _ind(
            "education",
            "education",
            "Schools & Institutes",
            "المدارس والمعاهد",
            ["training center", "private school", "language institute"],
            ["مركز تدريب", "مدرسة خاصة", "معهد لغات"],
            [("amenity", "school|college|language_school|training"), ("office", "educational_institution")],
        ),
        _ind(
            "nurseries",
            "education",
            "Nurseries & Kindergartens",
            "الحضانات ورياض الأطفال",
            ["nursery", "kindergarten", "daycare"],
            ["حضانة", "روضة أطفال"],
            [("amenity", "kindergarten|childcare")],
        ),
        _ind(
            "universities",
            "education",
            "Universities & Colleges",
            "الجامعات والكليات",
            ["university", "college"],
            ["جامعة", "كلية"],
            [("amenity", "university|college")],
        ),
        _ind(
            "tutoring",
            "education",
            "Tutoring Centers",
            "مراكز الدروس",
            ["tutoring center", "educational center"],
            ["مركز دروس خصوصية", "سنتر تعليمي", "مركز تعليمي"],
        ),
        # Beauty & fitness
        _ind(
            "beauty_salons",
            "beauty_fitness",
            "Beauty & Spa",
            "التجميل والسبا",
            ["beauty salon", "spa", "aesthetic clinic"],
            ["صالون تجميل", "سبا", "عيادة تجميل"],
            [("shop", "beauty|hairdresser|cosmetics"), ("leisure", "spa"), ("amenity", "spa")],
        ),
        _ind(
            "barbershops",
            "beauty_fitness",
            "Barbershops",
            "صالونات الحلاقة",
            ["barber shop", "men's salon"],
            ["حلاق", "صالون رجالي"],
            [("shop", "hairdresser")],
        ),
        _ind(
            "fitness",
            "beauty_fitness",
            "Gyms & Fitness",
            "النوادي الرياضية",
            ["gym", "fitness center"],
            ["نادي رياضي", "مركز لياقة"],
            [("leisure", "fitness_centre|sports_centre")],
        ),
        _ind(
            "sports_academies",
            "beauty_fitness",
            "Sports Academies",
            "الأكاديميات الرياضية",
            ["sports academy", "football academy", "swimming academy"],
            ["أكاديمية رياضية", "أكاديمية كرة قدم", "تعليم سباحة"],
            [("leisure", "sports_centre|sports_hall|swimming_pool")],
        ),
        # Automotive
        _ind(
            "automotive",
            "auto",
            "Car Dealers & Service",
            "معارض وصيانة السيارات",
            ["car dealership", "car service center"],
            ["معرض سيارات", "مركز صيانة سيارات"],
            [("shop", "car|car_repair|car_parts|tyres")],
        ),
        _ind(
            "car_rental",
            "auto",
            "Car Rental",
            "تأجير السيارات",
            ["car rental", "limousine service"],
            ["تأجير سيارات", "ليموزين"],
            [("amenity", "car_rental")],
        ),
        _ind(
            "car_wash",
            "auto",
            "Car Wash & Detailing",
            "مغاسل وتلميع السيارات",
            ["car wash", "car detailing"],
            ["مغسلة سيارات", "تلميع سيارات"],
            [("amenity", "car_wash")],
        ),
        _ind(
            "driving_schools",
            "auto",
            "Driving Schools",
            "مدارس تعليم القيادة",
            ["driving school"],
            ["مدرسة تعليم قيادة"],
            [("amenity", "driving_school")],
        ),
        # Industry & supply
        _ind(
            "manufacturing",
            "industrial",
            "Factories & Manufacturing",
            "المصانع",
            ["factory", "manufacturing company"],
            ["مصنع", "شركة تصنيع"],
            [("man_made", "works"), ("industrial", "factory|manufacturing")],
        ),
        _ind(
            "wholesale",
            "industrial",
            "Wholesale & Trading",
            "تجارة الجملة والتوزيع",
            ["wholesaler", "trading company", "distributor"],
            ["تاجر جملة", "شركة تجارية", "موزع"],
            [("shop", "wholesale")],
        ),
        _ind(
            "printing_packaging",
            "industrial",
            "Printing & Packaging",
            "الطباعة والتغليف",
            ["printing press", "packaging company"],
            ["مطبعة", "شركة تغليف"],
            [("shop", "copyshop"), ("craft", "printer")],
        ),
        _ind(
            "medical_supplies",
            "industrial",
            "Medical Supplies",
            "المستلزمات الطبية",
            ["medical supplies company", "medical equipment supplier"],
            ["شركة مستلزمات طبية", "أجهزة طبية"],
            [("shop", "medical_supply")],
        ),
        _ind(
            "security_services",
            "industrial",
            "Security & CCTV",
            "الحراسة وكاميرات المراقبة",
            ["security company", "CCTV installation"],
            ["شركة حراسات أمنية", "كاميرات مراقبة"],
            [("office", "security"), ("shop", "security")],
        ),
        # Logistics
        _ind(
            "logistics",
            "logistics",
            "Logistics & Freight",
            "الشحن والخدمات اللوجستية",
            ["logistics company", "freight forwarding"],
            ["شركة شحن", "خدمات لوجستية"],
            [("office", "logistics|moving_company|courier"), ("amenity", "post_depot")],
        ),
        _ind(
            "moving_companies",
            "logistics",
            "Moving Companies",
            "شركات نقل الأثاث",
            ["moving company", "furniture movers"],
            ["شركة نقل عفش", "نقل أثاث"],
            [("office", "moving_company")],
        ),
        # Hospitality & travel
        _ind(
            "hospitality",
            "travel",
            "Hotels & Hospitality",
            "الفنادق والضيافة",
            ["hotel", "serviced apartments"],
            ["فندق", "شقق فندقية"],
            [("tourism", "hotel|apartment|guest_house|motel")],
        ),
        _ind(
            "travel_agencies",
            "travel",
            "Travel & Umrah Agencies",
            "وكالات السفر والعمرة",
            ["travel agency", "umrah tours", "tour operator"],
            ["وكالة سفر", "شركة سياحة", "عمرة"],
            [("shop", "travel_agency"), ("office", "travel_agent")],
        ),
        # Tech & media
        _ind(
            "software_companies",
            "tech_media",
            "Software & IT Companies",
            "شركات البرمجيات والتقنية",
            ["software company", "IT company", "web development company"],
            ["شركة برمجيات", "شركة تقنية معلومات", "شركة تصميم مواقع"],
            [("office", "it|telecommunication")],
        ),
        _ind(
            "media_production",
            "tech_media",
            "Media & Photography",
            "الإنتاج الإعلامي والتصوير",
            ["video production company", "photography studio"],
            ["شركة إنتاج إعلامي", "استوديو تصوير"],
            [("craft", "photographer"), ("shop", "photo")],
        ),
        # Events
        _ind(
            "event_planning",
            "events",
            "Events & Exhibitions",
            "تنظيم الفعاليات والمعارض",
            ["event planner", "exhibition company", "conference organizer"],
            ["تنظيم فعاليات", "تنظيم معارض", "تنظيم مؤتمرات"],
        ),
        _ind(
            "wedding_services",
            "events",
            "Wedding Halls & Planners",
            "قاعات وتنظيم الأفراح",
            ["wedding hall", "wedding planner"],
            ["قاعة أفراح", "تنظيم حفلات زفاف", "قاعة مناسبات"],
            [("amenity", "events_venue")],
        ),
        # Home & facility services
        _ind(
            "cleaning",
            "home_services",
            "Cleaning & Pest Control",
            "التنظيف ومكافحة الحشرات",
            ["cleaning company", "pest control"],
            ["شركة تنظيف", "مكافحة حشرات"],
            [("craft", "cleaning")],
        ),
        _ind(
            "laundry",
            "home_services",
            "Laundry & Dry Cleaning",
            "المغاسل",
            ["laundry", "dry cleaning"],
            ["مغسلة ملابس", "دراي كلين"],
            [("shop", "laundry|dry_cleaning")],
        ),
        _ind(
            "maintenance",
            "home_services",
            "Maintenance & AC",
            "الصيانة والتكييف",
            ["maintenance company", "AC repair", "plumber", "electrician"],
            ["شركة صيانة", "صيانة مكيفات", "سباك", "كهربائي"],
            [("craft", "hvac|plumber|electrician")],
        ),
        _ind(
            "solar_energy",
            "home_services",
            "Solar Energy",
            "الطاقة الشمسية",
            ["solar energy company", "solar panels installer"],
            ["شركة طاقة شمسية", "تركيب ألواح شمسية"],
        ),
        # Agriculture
        _ind(
            "agriculture",
            "agriculture",
            "Farms & Agriculture",
            "المزارع والزراعة",
            ["farm", "agricultural company", "plant nursery"],
            ["مزرعة", "شركة زراعية", "مشتل"],
            [("shop", "garden_centre|agrarian")],
        ),
        # Organisations & workspaces
        _ind(
            "nonprofits",
            "community",
            "Charities & Non-profits",
            "الجمعيات الخيرية",
            ["charity", "non-profit organization"],
            ["جمعية خيرية", "مؤسسة غير ربحية"],
            [("office", "ngo|charity"), ("shop", "charity")],
        ),
        _ind(
            "coworking",
            "community",
            "Coworking & Business Centers",
            "مساحات العمل ومراكز الأعمال",
            ["coworking space", "business center"],
            ["مساحة عمل مشتركة", "مركز أعمال"],
            [("amenity", "coworking_space"), ("office", "coworking")],
        ),
    ]
}

# OpenStreetMap feature tags per industry (key, regex of values), used by the OSM provider.
OSM_TAGS: dict[str, list[tuple[str, str]]] = {k: v["osm"] for k, v in INDUSTRIES.items() if v.get("osm")}

# Tag keys an AI-planned search may use for OSM (values are validated as simple alternations).
OSM_TAG_KEYS = {"amenity", "shop", "office", "healthcare", "leisure", "tourism", "craft", "industrial", "man_made"}


class ProviderCategory(TypedDict):
    en: str
    ar: str
    offerings: list[tuple[str, str]]  # (en, ar) suggested offering names
    targets: list[str]  # suggested INDUSTRIES keys


# What kind of business the workspace itself runs: onboarding uses it to suggest offerings and target industries.
PROVIDER_CATEGORIES: dict[str, ProviderCategory] = {
    "marketing_agency": {
        "en": "Marketing / advertising agency",
        "ar": "وكالة تسويق أو إعلان",
        "offerings": [
            ("Social media management", "إدارة السوشيال ميديا"),
            ("Paid ads (Meta / Google / TikTok)", "إعلانات ممولة (ميتا / جوجل / تيك توك)"),
            ("Content & video production", "صناعة المحتوى والفيديو"),
            ("SEO", "تحسين الظهور في محركات البحث"),
        ],
        "targets": ["restaurants", "cafes", "beauty_salons", "dental_clinics", "real_estate", "fashion"],
    },
    "software": {
        "en": "Software / web development",
        "ar": "برمجة وتطوير مواقع وتطبيقات",
        "offerings": [
            ("Website development", "تصميم وتطوير المواقع"),
            ("Mobile apps", "تطبيقات الموبايل"),
            ("E-commerce stores", "المتاجر الإلكترونية"),
            ("Custom systems (ERP / CRM)", "أنظمة مخصصة (ERP / CRM)"),
        ],
        "targets": ["restaurants", "medical_clinics", "education", "real_estate", "wholesale", "automotive"],
    },
    "automation_ai": {
        "en": "Automation / AI solutions",
        "ar": "حلول الأتمتة والذكاء الاصطناعي",
        "offerings": [
            ("WhatsApp chatbot", "بوت واتساب للرد الآلي"),
            ("Online booking automation", "أتمتة الحجوزات"),
            ("CRM & sales automation", "أتمتة المبيعات وCRM"),
            ("AI customer support agent", "وكيل خدمة عملاء بالذكاء الاصطناعي"),
        ],
        "targets": ["dental_clinics", "medical_clinics", "beauty_salons", "real_estate", "fitness", "automotive"],
    },
    "design_branding": {
        "en": "Design / branding studio",
        "ar": "تصميم وهوية بصرية",
        "offerings": [
            ("Brand identity", "الهوية البصرية"),
            ("Packaging design", "تصميم التغليف"),
            ("Signage", "اللوحات واللافتات"),
        ],
        "targets": ["cafes", "restaurants", "bakeries", "perfumes", "fashion", "food_supply"],
    },
    "accounting_finance": {
        "en": "Accounting / finance services",
        "ar": "خدمات محاسبة ومالية",
        "offerings": [
            ("Bookkeeping", "مسك الدفاتر"),
            ("VAT & tax filing", "الإقرارات الضريبية"),
            ("Payroll", "إدارة الرواتب"),
            ("Company formation", "تأسيس الشركات"),
        ],
        "targets": ["restaurants", "construction", "wholesale", "ecommerce", "medical_clinics", "logistics"],
    },
    "legal_services": {
        "en": "Legal services",
        "ar": "خدمات قانونية",
        "offerings": [
            ("Contracts & corporate law", "العقود وقانون الشركات"),
            ("Trademark registration", "تسجيل العلامات التجارية"),
            ("Debt collection", "تحصيل المديونيات"),
        ],
        "targets": ["real_estate", "construction", "ecommerce", "wholesale", "software_companies"],
    },
    "consulting_training": {
        "en": "Consulting / corporate training",
        "ar": "استشارات وتدريب شركات",
        "offerings": [
            ("Management consulting", "استشارات إدارية"),
            ("Staff training", "تدريب الموظفين"),
            ("Quality certification (ISO)", "شهادات الجودة (ISO)"),
        ],
        "targets": ["hospitals", "manufacturing", "construction", "hospitality", "education"],
    },
    "recruitment_hr": {
        "en": "Recruitment / HR services",
        "ar": "توظيف وموارد بشرية",
        "offerings": [
            ("Recruitment", "التوظيف"),
            ("Outsourced staffing", "توفير عمالة"),
            ("HR outsourcing", "إدارة الموارد البشرية"),
        ],
        "targets": ["restaurants", "hospitality", "construction", "cleaning", "hospitals", "supermarkets"],
    },
    "b2b_supplier": {
        "en": "B2B supplier / distributor",
        "ar": "مورد أو موزع للشركات",
        "offerings": [("Product supply", "توريد منتجات"), ("Wholesale distribution", "توزيع بالجملة")],
        "targets": ["restaurants", "cafes", "supermarkets", "hospitals", "pharmacies", "hospitality"],
    },
    "medical_supplier": {
        "en": "Medical / dental supplier",
        "ar": "توريدات طبية أو أسنان",
        "offerings": [
            ("Medical equipment", "أجهزة طبية"),
            ("Dental supplies", "مستلزمات الأسنان"),
            ("Medical consumables", "مستهلكات طبية"),
        ],
        "targets": ["dental_clinics", "medical_clinics", "hospitals", "laboratories", "pharmacies", "veterinary"],
    },
    "facility_services": {
        "en": "Cleaning / maintenance / facility services",
        "ar": "نظافة وصيانة وإدارة مرافق",
        "offerings": [
            ("Commercial cleaning", "تنظيف المنشآت"),
            ("Maintenance contracts", "عقود الصيانة"),
            ("Pest control", "مكافحة الحشرات"),
        ],
        "targets": ["restaurants", "hospitality", "medical_clinics", "education", "coworking", "supermarkets"],
    },
    "printing_packaging": {
        "en": "Printing / packaging",
        "ar": "طباعة وتغليف",
        "offerings": [
            ("Commercial printing", "الطباعة التجارية"),
            ("Custom packaging", "تغليف مخصص"),
            ("Promotional items", "الهدايا الدعائية"),
        ],
        "targets": ["restaurants", "cafes", "bakeries", "ecommerce", "perfumes", "event_planning"],
    },
    "photo_video": {
        "en": "Photography / video production",
        "ar": "تصوير وإنتاج فيديو",
        "offerings": [
            ("Product photography", "تصوير المنتجات"),
            ("Promotional videos", "فيديوهات دعائية"),
            ("Event coverage", "تغطية الفعاليات"),
        ],
        "targets": ["restaurants", "real_estate", "fashion", "hospitality", "event_planning", "automotive"],
    },
    "logistics_delivery": {
        "en": "Logistics / delivery",
        "ar": "شحن وتوصيل",
        "offerings": [
            ("Last-mile delivery", "التوصيل للعملاء"),
            ("Warehousing", "التخزين"),
            ("Freight & customs clearance", "الشحن والتخليص الجمركي"),
        ],
        "targets": ["ecommerce", "wholesale", "manufacturing", "restaurants", "pharmacies"],
    },
    "security_it": {
        "en": "Security / IT infrastructure",
        "ar": "أنظمة أمن وبنية تحتية تقنية",
        "offerings": [
            ("CCTV installation", "تركيب كاميرات المراقبة"),
            ("Networks & IT support", "الشبكات والدعم الفني"),
            ("Access control", "أنظمة التحكم في الدخول"),
        ],
        "targets": ["supermarkets", "education", "hospitality", "manufacturing", "medical_clinics"],
    },
    "other": {"en": "Other", "ar": "أخرى", "offerings": [], "targets": []},
}


# Directories whose listing pages the "directories" source reads: (country or "*", industry group or "*", site).
# Extend without code through DIRECTORY_SITES="EG:education:example.com;SA:*:other.sa" (config.directory_sites).
DIRECTORIES: list[tuple[str, str, str]] = [
    ("EG", "*", "yellowpages.com.eg"),
    ("EG", "health", "vezeeta.com"),
    ("EG", "food", "elmenus.com"),
    ("EG", "property", "aqarmap.com.eg"),
    ("EG", "property", "propertyfinder.eg"),
    ("SA", "health", "vezeeta.com"),
    ("SA", "property", "bayut.sa"),
    ("SA", "property", "propertyfinder.sa"),
    ("AE", "*", "yellowpages-uae.com"),
    ("AE", "*", "connect.ae"),
    ("AE", "property", "bayut.com"),
    ("AE", "property", "propertyfinder.ae"),
    ("JO", "health", "vezeeta.com"),
    ("LB", "health", "vezeeta.com"),
    ("QA", "property", "propertyfinder.qa"),
    ("BH", "property", "propertyfinder.bh"),
    ("*", "beauty_fitness", "fresha.com"),
]


def directory_sites(country: str, industry: str | None = None, group: str | None = None) -> list[str]:
    from app.core.config import get_settings

    rows = list(DIRECTORIES)
    for item in (get_settings().directory_sites or "").split(";"):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) == 3 and all(parts):
            rows.append((parts[0].upper(), parts[1], parts[2].lower()))
    group = group or INDUSTRIES.get(industry or "", {}).get("group")
    out = [site for c, g, site in rows if c in ("*", country.upper()) and (g == "*" or g == group or g == industry)]
    return list(dict.fromkeys(out))


# Who decides in each kind of prospect business, in English and Arabic (searched for and ranked first).
GROUP_DECISION_ROLES: dict[str, list[str]] = {
    "health": ["Medical Director", "Clinic Manager", "Hospital Director", "المدير الطبي", "مدير العيادة"],
    "education": ["Principal", "School Director", "Dean", "مدير المدرسة", "ناظر المدرسة", "صاحب المدرسة"],
    "food": ["General Manager", "Operations Manager", "مدير العمليات"],
    "retail": ["Store Manager", "Purchasing Manager", "مدير المشتريات"],
    "professional": ["Managing Partner", "Partner", "الشريك المدير"],
    "property": ["Managing Director", "Project Manager", "مدير المشاريع"],
    "beauty_fitness": ["Branch Manager", "مدير الفرع"],
    "auto": ["General Manager", "Branch Manager", "مدير الفرع"],
    "industrial": ["Plant Manager", "Procurement Manager", "Managing Director", "مدير المصنع", "مدير المشتريات"],
    "logistics": ["Operations Manager", "Managing Director", "مدير العمليات"],
    "travel": ["General Manager", "Hotel Manager", "مدير الفندق"],
    "tech_media": ["CTO", "Managing Director"],
    "events": ["Managing Director"],
    "home_services": ["Operations Manager", "مدير العمليات"],
    "agriculture": ["Farm Manager", "مدير المزرعة"],
    "community": ["Executive Director", "المدير التنفيذي"],
}

# Who buys what the seller offers, by the seller's own category (PROVIDER_CATEGORIES keys).
BUYER_ROLES: dict[str, list[str]] = {
    "marketing_agency": ["Marketing Manager", "Head of Marketing", "مدير التسويق"],
    "software": ["IT Manager", "CTO", "مدير تقنية المعلومات"],
    "automation_ai": ["Operations Manager", "مدير العمليات"],
    "design_branding": ["Marketing Manager", "مدير التسويق"],
    "accounting_finance": ["Finance Manager", "CFO", "Financial Controller", "المدير المالي"],
    "legal_services": ["Legal Manager", "General Counsel", "المستشار القانوني"],
    "consulting_training": ["HR Manager", "Training Manager", "مدير الموارد البشرية", "مدير التدريب"],
    "recruitment_hr": ["HR Manager", "Human Resources Manager", "مدير الموارد البشرية"],
    "medical_supplier": ["Procurement Manager", "Purchasing Manager", "مدير المشتريات", "مسؤول المشتريات"],
    "facility_services": ["Facility Manager", "Operations Manager", "مدير المرافق"],
    "printing_packaging": ["Marketing Manager", "Purchasing Manager", "مدير المشتريات"],
    "photo_video": ["Marketing Manager", "مدير التسويق"],
    "logistics_delivery": ["Operations Manager", "Supply Chain Manager", "مدير سلاسل الإمداد"],
    "security_it": ["IT Manager", "Facility Manager", "مدير تقنية المعلومات"],
}


def decision_roles(
    industry: str | None, seller_category: str | None = None, extra: list[str] | None = None
) -> list[str]:
    """Roles to look for at a prospect: what the campaign asked for, who buys the seller's offer, who runs the
    prospect's kind of business. Owners/founders/CEOs are always looked for on top (decision_makers.py)."""
    group = INDUSTRIES.get(industry or "", {}).get("group")
    roles = [*(extra or []), *BUYER_ROLES.get(seller_category or "", []), *GROUP_DECISION_ROLES.get(group or "", [])]
    return list(dict.fromkeys(r.strip() for r in roles if r and r.strip()))[:12]


# The fixed service list the product originally shipped with. Kept only so old campaigns/assessments that
# stored these keys still get readable labels; workspaces now define their own offerings (services/profile.py).
LEGACY_SERVICES: dict[str, dict[str, str]] = {
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


def is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def industry_terms(industry: str) -> tuple[list[str], list[str]]:
    """Return (english_terms, arabic_terms) for a catalog key or free-text industry."""
    item = INDUSTRIES.get(industry)
    if item:
        return item["terms_en"], item["terms_ar"]
    return ([], [industry]) if is_arabic(industry) else ([industry], [])


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


def place_names(country: str, city: str | None, region: str | None = None) -> tuple[str, str]:
    """(English, Arabic) place for search queries: the city, else the region/governorate, else the country.

    Places missing from the catalog (any governorate, district or town) are used as typed in both languages."""
    city_en, city_ar = city_names(country, city)
    if city and city_ar is None and is_arabic(city):
        city_en, city_ar = None, city
    region_en = region if region and not is_arabic(region) else None
    region_ar = region if region and is_arabic(region) else None
    country_en, country_ar = country_names(country)
    en = city_en or region_en or city_ar or region_ar or country_en
    ar = city_ar or region_ar or city_en or region_en or country_ar or country_en
    return en, ar


def country_names(country: str) -> tuple[str, str | None]:
    c = COUNTRIES.get(country.upper())
    return (c["name_en"], c["name_ar"]) if c else (country, None)
