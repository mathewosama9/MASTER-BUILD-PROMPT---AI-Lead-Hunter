"""Parse an uploaded CSV/XLSX list of businesses into validated import rows (English or Arabic headers)."""

import csv
import io
import json
import re

from app.research.enrichment.contacts import social_profile_url
from app.research.enrichment.normalize import business_domain, normalize_email

MAX_ROWS = 1000
SOCIAL_COLUMNS = ("instagram", "facebook", "snapchat", "tiktok", "linkedin", "x")
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "company", "business", "business name", "company name", "الاسم", "اسم الشركة", "الشركة", "النشاط"),
    "website": ("website", "site", "url", "web", "domain", "الموقع", "الموقع الإلكتروني", "الموقع الالكتروني"),
    "phone": (
        "phone",
        "telephone",
        "mobile",
        "tel",
        "whatsapp",
        "الهاتف",
        "التليفون",
        "الجوال",
        "رقم الهاتف",
        "موبايل",
    ),
    "email": ("email", "e-mail", "mail", "البريد", "البريد الإلكتروني", "الايميل", "الإيميل"),
    "city": ("city", "المدينة"),
    "address": ("address", "العنوان"),
    "instagram": ("instagram", "ig", "انستجرام", "انستغرام", "إنستغرام"),
    "facebook": ("facebook", "fb", "فيسبوك", "فيس بوك"),
    "snapchat": ("snapchat", "snap", "سناب", "سناب شات"),
    "tiktok": ("tiktok", "tik tok", "تيك توك"),
    "linkedin": ("linkedin", "لينكدان", "لينكد إن"),
    "x": ("x", "twitter", "تويتر"),
}
SOCIAL_BASE = {
    "instagram": "https://www.instagram.com/{}",
    "facebook": "https://www.facebook.com/{}",
    "snapchat": "https://www.snapchat.com/add/{}",
    "tiktok": "https://www.tiktok.com/@{}",
    "linkedin": "https://www.linkedin.com/company/{}",
    "x": "https://x.com/{}",
}


class ImportError_(ValueError):
    pass


def _canonical_header(h: str) -> str | None:
    key = re.sub(r"\s+", " ", (h or "").strip().lower().replace("_", " "))
    for field, aliases in HEADER_ALIASES.items():
        if key in aliases:
            return field
    return None


def _read_table(filename: str, content: bytes) -> list[list[str]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - corrupt/unsupported workbook
            raise ImportError_(f"Could not read the Excel file: {exc}") from exc
        ws = wb.worksheets[0]
        rows = [["" if v is None else str(v).strip() for v in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    if name.endswith((".csv", ".txt")):
        for enc in ("utf-8-sig", "cp1256", "latin-1"):  # cp1256: Arabic Windows exports from Excel
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel  # sniffing fails on sparse rows; comma is the safe default
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    raise ImportError_("Unsupported file type. Upload .csv or .xlsx")


def _social(field: str, value: str) -> str | None:
    v = value.strip()
    if not v:
        return None
    # "instagram.com/x" or a full URL is a link; anything else ("@x", "x", "x.y") is a handle.
    url = (v if "://" in v else f"https://{v}") if "/" in v else SOCIAL_BASE[field].format(v.lstrip("@"))
    platform, canon = social_profile_url(url)
    return canon if platform else None


def parse_import(filename: str, content: bytes) -> tuple[list[dict], list[dict]]:
    """Return (rows, rejected). Each row: name, website, phone, email, city, address, social_urls."""
    table = [r for r in _read_table(filename, content) if any(c for c in r)]
    if not table:
        raise ImportError_("The file is empty")
    header = [_canonical_header(h) for h in table[0]]
    if "name" not in header:
        raise ImportError_("A 'name' column (or الاسم) is required in the first row")
    rows: list[dict] = []
    rejected: list[dict] = []
    for line_no, raw in enumerate(table[1:], start=2):
        rec = {f: raw[i].strip() for i, f in enumerate(header) if f and i < len(raw) and raw[i].strip()}
        reason = None
        website = rec.get("website")
        if website and not business_domain(website if "://" in website else f"https://{website}"):
            website, reason = None, "website is not a business domain (ignored)"
        email = normalize_email(rec["email"]) if rec.get("email") else None
        socials = [s for f in SOCIAL_COLUMNS if (s := _social(f, rec.get(f, "")))]
        if not rec.get("name"):
            rejected.append({"line": line_no, "reason": "missing name"})
            continue
        if not (website or rec.get("phone") or email or socials):
            rejected.append({"line": line_no, "reason": "needs at least a website, phone, email or social profile"})
            continue
        if len(rows) >= MAX_ROWS:
            rejected.append({"line": line_no, "reason": f"over the {MAX_ROWS}-row limit"})
            continue
        row = {
            "name": rec["name"][:300],
            "website": (website if "://" in (website or "") else f"https://{website}") if website else None,
            "phone": rec.get("phone"),
            "email": email,
            "city": rec.get("city"),
            "address": rec.get("address"),
            "social_urls": socials,
            "line": line_no,
        }
        if reason:
            row["warning"] = reason
        rows.append(row)
    return rows, rejected


def encode_rows(rows: list[dict]) -> list[str]:
    """Rows travel in CampaignSource.manual_urls as compact JSON strings (no schema change needed)."""
    return [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]
