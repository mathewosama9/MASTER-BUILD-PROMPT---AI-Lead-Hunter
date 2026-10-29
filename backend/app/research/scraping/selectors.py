"""Every CSS selector the scrapers depend on, in one place.

Google and Meta change their markup often. When a field stops parsing, fix it here; each field lists
fallbacks in priority order. Pages are loaded with hl=en so aria-labels stay in English.
"""

MAPS = {
    "feed": 'div[role="feed"]',
    "result_link": 'a.hfpxzc, a[href*="/maps/place/"]',
    "end_of_list": "span.HlvSq, p.fontBodyMedium > span > span",
    "name": ["h1.DUwDvf", "h1"],
    "rating_box": ["div.F7nice", 'div[jsaction*="reviewChart"]'],
    "category": ['button[jsaction*="category"]', "span.DkEaL"],
    "address": ['button[data-item-id="address"]'],
    "website": ['a[data-item-id="authority"]'],
    "phone": ['button[data-item-id^="phone:tel:"]'],
    "plus_code": ['button[data-item-id="oloc"]'],
    "hours": ["div.t39EBf[aria-label]", 'div[aria-label*="Hide open hours"]', "table.eK4R0e"],
    "consent_reject": [
        'form[action*="consent"] button[aria-label*="Reject"]',
        'button[aria-label*="Reject all"]',
        'form[action*="consent"] button',
    ],
}

# Markers that mean "blocked / challenge / login wall" rather than real content.
BLOCK_MARKERS = (
    "our systems have detected unusual traffic",
    "/sorry/index",
    "g-recaptcha",
    "captcha-form",
    "are you a robot",
)
LOGIN_MARKERS = {
    "instagram": ("/accounts/login", "Login • Instagram"),
    "facebook": ("/login/?next", "You must log in to continue", "log in to facebook"),
    "tiktok": ("/login?redirect", "SlardarWAF", "_wafchallengeid"),
    "linkedin": ("/authwall", "linkedin.com/login", "Sign Up | LinkedIn", "/checkpoint/", "/uas/login"),
    "x": ("/i/flow/login",),
}
