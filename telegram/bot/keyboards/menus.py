from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from bot.i18n import t

WIZARD_INDUSTRIES = ["medical_clinics", "dental_clinics", "real_estate", "ecommerce", "restaurants", "education"]
# File import and manual URLs need the dashboard (file upload / URL list), so they are not offered here.
SOURCE_LABELS = {"demo": "🧪 Demo fixtures", "google_maps": "📍 Google Maps", "osm": "🗺️ OpenStreetMap (free)",
                 "brave": "🔍 Web Search", "hunter": "📇 Licensed Directories (Hunter)", "x": "𝕏 X API"}


def dashboard_button(lang: str, path: str = "") -> InlineKeyboardButton | None:
    url = get_settings().frontend_url.rstrip("/") + path
    # Telegram only accepts public https URLs for URL buttons.
    if not url.startswith("https://"):
        return None
    return InlineKeyboardButton(text=t("btn_dashboard", lang), url=url)


def main_menu(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_new", lang), callback_data="m:new")
    b.button(text=t("btn_mine", lang), callback_data="m:mine")
    b.button(text=t("btn_results", lang), callback_data="m:results")
    b.button(text=t("btn_top", lang), callback_data="m:top")
    b.button(text=t("btn_stats", lang), callback_data="m:stats")
    b.button(text=t("btn_export", lang), callback_data="m:export")
    b.button(text=t("btn_settings", lang), callback_data="m:settings")
    b.button(text=t("btn_help", lang), callback_data="m:help")
    b.adjust(2)
    dash = dashboard_button(lang)
    if dash:
        b.row(dash)
    return b.as_markup()


def countries_kb(meta: dict, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in meta["countries"]:
        b.button(text=c["name_ar"] if lang == "ar" else c["name_en"], callback_data=f"w:country:{c['code']}")
    b.button(text=t("other", lang), callback_data="w:country:other")
    b.button(text=t("cancel", lang), callback_data="w:cancel")
    b.adjust(3, 1, 1)
    return b.as_markup()


def cities_kb(meta: dict, country: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    c = next((x for x in meta["countries"] if x["code"] == country), None)
    for i, city in enumerate((c or {}).get("cities", [])[:9]):
        b.button(text=city["ar"] if lang == "ar" else city["en"], callback_data=f"w:city:{i}")
    b.button(text=t("skip", lang), callback_data="w:city:skip")
    b.adjust(3)
    return b.as_markup()


def industries_kb(meta: dict, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    names = {i["key"]: (i["ar"] if lang == "ar" else i["en"]) for i in meta["industries"]}
    for key in WIZARD_INDUSTRIES:
        b.button(text=names.get(key, key), callback_data=f"w:ind:{key}")
    b.button(text=t("custom", lang) + " Industry" if lang == "en" else t("custom", lang), callback_data="w:ind:custom")
    b.adjust(2)
    return b.as_markup()


def sources_kb(providers: list[dict], selected: set[str], lang: str, demo_mode: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, label in SOURCE_LABELS.items():
        if key == "demo" and not demo_mode:
            continue
        p = next((x for x in providers if x["key"] == key), None)
        ok = p is not None and p["status"] == "connected"
        mark = "☑️" if key in selected else ("✅" if ok else "⛔")
        b.button(text=f"{mark} {label}", callback_data=f"w:src:{key}")
    b.button(text=t("done", lang), callback_data="w:src:done")
    b.adjust(1)
    return b.as_markup()


def count_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in (20, 50, 100):
        b.button(text=str(n), callback_data=f"w:count:{n}")
    b.button(text=t("custom", lang), callback_data="w:count:custom")
    b.adjust(4)
    return b.as_markup()


def yes_no_kb(lang: str, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("yes", lang), callback_data=f"{prefix}:yes")
    b.button(text=t("no", lang), callback_data=f"{prefix}:no")
    return b.as_markup()


def confirm_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("start_research", lang), callback_data="w:go")
    b.button(text=t("edit", lang), callback_data="w:edit")
    b.button(text=t("cancel", lang), callback_data="w:cancel")
    b.adjust(1)
    return b.as_markup()


def campaign_kb(cid: str, status: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    running = status in ("queued", "discovering", "enriching", "analyzing")
    if running:
        b.button(text="🔄 View Progress", callback_data=f"c:prog:{cid}")
        b.button(text="⏸ Pause", callback_data=f"c:pause:{cid}")
        b.button(text="✖ Cancel", callback_data=f"c:cancel:{cid}")
    elif status == "paused":
        b.button(text="▶️ Resume", callback_data=f"c:resume:{cid}")
        b.button(text="✖ Cancel", callback_data=f"c:cancel:{cid}")
    else:
        b.button(text="📋 View Results", callback_data=f"c:res:{cid}")
        b.button(text="📤 Export CSV", callback_data=f"c:csv:{cid}")
        b.button(text="🏆 Top 10 Leads", callback_data=f"c:top:{cid}")
        if status in ("failed", "partially_completed"):
            b.button(text="🔁 Retry failures", callback_data=f"c:retry:{cid}")
    b.adjust(2)
    dash = dashboard_button(lang, f"/campaigns/{cid}")
    if dash:
        b.row(dash)
    b.row(InlineKeyboardButton(text=t("back", lang), callback_data="m:menu"))
    return b.as_markup()
