"""Inline keyboards. callback_data scheme (each value stays under Telegram's 64-byte limit):

m:<item>              main menu items
w:<step>[:<value>]    new-search wizard (w:back, w:cancel, w:ai, w:go, w:edit:<field>)
c:<action>:<id|page>  campaigns (c:prog/pause/resume/cancel/retry/res/top/csv are also sent by the worker)
l:<action>:...        leads: l:p:<page>:<qualified 0|1>[:<campaign>], l:v:<id>, l:s:<id>, l:st:<id>:<status>,
                      l:n:<id>, l:back
b:<action>[:<value>]  credits: b:bal, b:pkgs, b:pkg:<id>, b:mth:<method>, b:skipref, b:cancel
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from bot.i18n import CRM, RUNNING, label, num, t

CITIES_PER_PAGE = 9
INDUSTRIES_PER_PAGE = 8
# The bot never offers Do Not Contact: it suppresses the business and only an admin can undo it (dashboard).
BOT_CRM_STATUSES = [k for k in CRM if k != "do_not_contact"]


def web_url(path: str = "/app") -> str | None:
    url = get_settings().frontend_url.rstrip("/") + path
    # Telegram only accepts public https URLs for URL buttons.
    return url if url.startswith("https://") else None


def dashboard_button(lang: str, path: str = "/app") -> InlineKeyboardButton | None:
    url = web_url(path)
    return InlineKeyboardButton(text=t("btn_dashboard", lang), url=url) if url else None


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def menu_row(lang: str) -> list[InlineKeyboardButton]:
    return [_btn(t("menu", lang), "m:menu")]


def main_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [_btn(t("btn_new", lang), "m:new")],
        [_btn(t("btn_mine", lang), "m:mine"), _btn(t("btn_top", lang), "m:top")],
        [_btn(t("btn_balance", lang), "b:bal"), _btn(t("btn_export", lang), "m:export")],
        [_btn(t("btn_settings", lang), "m:settings"), _btn(t("btn_help", lang), "m:help")],
    ]
    dash = dashboard_button(lang)
    if dash:
        rows.append([dash])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[menu_row(lang)])


def unlinked_kb(lang: str) -> InlineKeyboardMarkup | None:
    rows = []
    register = web_url("/register")
    link_page = web_url("/app/settings?tab=telegram")
    if register:
        rows.append([InlineKeyboardButton(text=t("btn_register", lang), url=register)])
    if link_page:
        rows.append([InlineKeyboardButton(text=t("btn_link_page", lang), url=link_page)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def settings_kb(lang: str) -> InlineKeyboardMarkup:
    rows = [[_btn(t("btn_lang", lang), "m:lang")]]
    dash = dashboard_button(lang, "/app/settings")
    if dash:
        rows.append([dash])
    rows.append(menu_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Wizard ------------------------------------------------------------------------------------------------

def _nav(b: InlineKeyboardBuilder, lang: str, back: bool = True) -> None:
    row = [_btn(t("back", lang), "w:back")] if back else []
    row.append(_btn(t("cancel", lang), "w:cancel"))
    b.row(*row)


def _pager(b: InlineKeyboardBuilder, prefix: str, page: int, pages: int, lang: str) -> None:
    if pages <= 1:
        return
    row = []
    if page > 0:
        row.append(_btn(t("prev", lang), f"{prefix}:{page - 1}"))
    row.append(_btn(f"{page + 1}/{pages}", "w:noop"))
    if page < pages - 1:
        row.append(_btn(t("next", lang), f"{prefix}:{page + 1}"))
    b.row(*row)


def mode_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(_btn(t("btn_free_text", lang), "w:mode:text"))
    b.row(_btn(t("btn_steps", lang), "w:mode:steps"))
    _nav(b, lang, back=False)
    return b.as_markup()


def text_input_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _nav(b, lang)
    return b.as_markup()


def countries_kb(meta: dict, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in meta["countries"]:
        b.button(text=c["name_ar"] if lang == "ar" else c["name_en"], callback_data=f"w:country:{c['code']}")
    b.adjust(3)
    b.row(_btn(t("other_country", lang), "w:country:other"))
    _nav(b, lang)
    return b.as_markup()


def cities_kb(meta: dict, country: str, lang: str, page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    c = next((x for x in meta["countries"] if x["code"] == country), None)
    cities = (c or {}).get("cities", [])
    pages = max(1, -(-len(cities) // CITIES_PER_PAGE))
    page = max(0, min(page, pages - 1))
    start = page * CITIES_PER_PAGE
    for i, city in enumerate(cities[start:start + CITIES_PER_PAGE], start):
        b.button(text=city["ar"] if lang == "ar" else city["en"], callback_data=f"w:city:{i}")
    b.adjust(3)
    _pager(b, "w:cpage", page, pages, lang)
    b.row(_btn(t("whole_country", lang), "w:city:skip"), _btn(t("other_city", lang), "w:city:other"))
    _nav(b, lang)
    return b.as_markup()


def industries_kb(meta: dict, lang: str, page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    items = meta["industries"]
    pages = max(1, -(-len(items) // INDUSTRIES_PER_PAGE))
    page = max(0, min(page, pages - 1))
    start = page * INDUSTRIES_PER_PAGE
    for i in items[start:start + INDUSTRIES_PER_PAGE]:
        b.button(text=i["ar"] if lang == "ar" else i["en"], callback_data=f"w:ind:{i['key']}")
    b.adjust(2)
    _pager(b, "w:ipage", page, pages, lang)
    b.row(_btn(t("custom_industry", lang), "w:ind:custom"))
    _nav(b, lang)
    return b.as_markup()


def count_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in (20, 50, 100):
        b.button(text=str(n), callback_data=f"w:count:{n}")
    b.button(text=t("custom", lang), callback_data="w:count:custom")
    b.adjust(4)
    _nav(b, lang)
    return b.as_markup()


def summary_kb(lang: str, ai: bool, can_start: bool, need_topup: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if can_start:
        b.row(_btn(t("btn_start", lang), "w:go"))
    if need_topup:
        b.row(_btn(t("btn_topup", lang), "b:pkgs"))
    b.row(_btn(t("btn_toggle_ai", lang, v=t("on" if ai else "off", lang)), "w:ai"))
    b.row(_btn(t("btn_edit_place", lang), "w:edit:country"), _btn(t("btn_edit_industry", lang), "w:edit:industry"))
    b.row(_btn(t("btn_edit_count", lang), "w:edit:count"))
    _nav(b, lang)
    return b.as_markup()


# Campaigns ---------------------------------------------------------------------------------------------

def campaigns_kb(items: list[dict], page: int, pages: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, c in enumerate(items, 1):
        b.button(text=str(i), callback_data=f"c:view:{c['id']}")
    b.adjust(6)
    nav = []
    if page > 1:
        nav.append(_btn(t("prev", lang), f"c:list:{page - 1}"))
    if page < pages:
        nav.append(_btn(t("next", lang), f"c:list:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(_btn(t("btn_new", lang), "m:new"), *menu_row(lang))
    return b.as_markup()


def campaign_kb(cid: str, status: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if status in RUNNING:
        b.row(_btn(t("btn_progress", lang), f"c:prog:{cid}"))
        b.row(_btn(t("btn_pause", lang), f"c:pause:{cid}"), _btn(t("btn_stop", lang), f"c:cancel:{cid}"))
    elif status == "paused":
        b.row(_btn(t("btn_resume", lang), f"c:resume:{cid}"), _btn(t("btn_stop", lang), f"c:cancel:{cid}"))
    else:
        b.row(_btn(t("btn_best", lang), f"c:top:{cid}"), _btn(t("btn_results", lang), f"c:res:{cid}"))
        b.row(_btn(t("btn_csv", lang), f"c:csv:{cid}"))
        if status in ("failed", "partially_completed"):
            b.row(_btn(t("btn_retry", lang), f"c:retry:{cid}"))
    dash = dashboard_button(lang, f"/app/campaigns/{cid}")
    if dash:
        b.row(dash)
    b.row(_btn(t("btn_all_campaigns", lang), "c:list:1"), *menu_row(lang))
    return b.as_markup()


# Leads -------------------------------------------------------------------------------------------------

def leads_kb(items: list[dict], page: int, pages: int, qualified: bool, cid: str | None,
             lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, x in enumerate(items, 1):
        b.button(text=str(i), callback_data=f"l:v:{x['id']}")
    b.adjust(5)
    q = 1 if qualified else 0
    suffix = f":{cid}" if cid else ""
    nav = []
    if page > 1:
        nav.append(_btn(t("prev", lang), f"l:p:{page - 1}:{q}{suffix}"))
    if pages > 1:
        nav.append(_btn(f"{page}/{pages}", "w:noop"))
    if page < pages:
        nav.append(_btn(t("next", lang), f"l:p:{page + 1}:{q}{suffix}"))
    if nav:
        b.row(*nav)
    if cid:
        b.row(_btn(t("back", lang), f"c:view:{cid}"), *menu_row(lang))
    else:
        b.row(*menu_row(lang))
    return b.as_markup()


def lead_kb(lead_id: str, lang: str, whatsapp: str | None, website: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    links = []
    if whatsapp:
        links.append(InlineKeyboardButton(text=t("btn_whatsapp", lang), url=f"https://wa.me/{whatsapp}"))
    if website and website.startswith(("http://", "https://")):
        links.append(InlineKeyboardButton(text=t("btn_website", lang), url=website))
    if links:
        b.row(*links)
    b.row(_btn(t("btn_status", lang), f"l:s:{lead_id}"), _btn(t("btn_note", lang), f"l:n:{lead_id}"))
    dash = dashboard_button(lang, f"/app/leads/{lead_id}")
    if dash:
        b.row(dash)
    b.row(_btn(t("btn_back_list", lang), "l:back"), *menu_row(lang))
    return b.as_markup()


def crm_kb(lead_id: str, current: str | None, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key in BOT_CRM_STATUSES:
        text = label(CRM, key, lang) + (" ✓" if key == current else "")
        b.button(text=text, callback_data=f"l:st:{lead_id}:{key}")
    b.adjust(2)
    b.row(_btn(t("back", lang), f"l:v:{lead_id}"))
    return b.as_markup()


def note_kb(lead_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(t("cancel", lang), f"l:v:{lead_id}")]])


def export_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("btn_export_qualified", lang), "m:export:qualified")],
        [_btn(t("btn_mine", lang), "c:list:1")],
        menu_row(lang),
    ])


# Credits -----------------------------------------------------------------------------------------------

def balance_kb(lang: str, can_topup: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_topup:
        rows.append([_btn(t("btn_topup", lang), "b:pkgs")])
    dash = dashboard_button(lang, "/app/billing")
    if dash:
        rows.append([dash])
    rows.append(menu_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def packages_kb(packages: list[dict], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in packages:
        name = p["name_ar"] if lang == "ar" else p["name_en"]
        text = t("package_btn", lang, name=name, credits=num(p["credits"]), price=money_text(p["price"], p["currency"]))
        b.row(_btn(("⭐ " if p.get("featured") else "") + text, f"b:pkg:{p['id']}"))
    b.row(_btn(t("back", lang), "b:bal"), _btn(t("cancel", lang), "b:cancel"))
    return b.as_markup()


def pay_kb(lang: str, url: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if url:
        b.row(InlineKeyboardButton(text=t("btn_pay_paypal", lang), url=url))
    b.row(_btn(t("back", lang), "b:pkgs"), _btn(t("cancel", lang), "b:cancel"))
    return b.as_markup()


def money_text(value: object, currency: str) -> str:
    """A store price: "$15" for US dollars, "15 EUR" otherwise."""
    amount = price_text(value)
    return f"${amount}" if currency == "USD" else f"{amount} {currency}"


def price_text(value: object) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{f:,.0f}" if f == int(f) else f"{f:,.2f}"
