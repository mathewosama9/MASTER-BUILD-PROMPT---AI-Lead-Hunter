"""Headless Chromium session shared by the scrapers of one campaign run.

Polite by construction: one page at a time, a random 2-5 s pause between navigations, a hard page budget.
A challenge/captcha page raises `ScrapeBlocked`; it is never solved or evaded.
"""

import asyncio
import logging
import random
from typing import Any, Protocol

from app.core.config import get_settings
from app.research.geo import Place, country_place
from app.research.scraping.parsers import ScrapeBlocked, is_blocked
from app.research.scraping.selectors import MAPS

log = logging.getLogger(__name__)


class PageSource(Protocol):
    """What the scrapers need from a browser. Tests provide a fake implementation."""

    async def open(self, url: str, wait_for: str | None = None, session: str | None = None) -> tuple[str, str]: ...

    async def scroll_feed(self, selector: str, max_rounds: int, stop_text: str | None = None) -> str: ...

    async def close(self) -> None: ...


class BrowserUnavailable(Exception):
    pass


class BrowserSession:
    def __init__(
        self,
        country: str | None = None,
        max_pages: int | None = None,
        sessions: dict[str, dict] | None = None,
        place: Place | None = None,
    ) -> None:
        s = get_settings()
        # Browse as a user inside the target market: its timezone and region, the city as geolocation.
        self.place = place or country_place(country)
        self.locale, self.timezone = self.place.browser_locale, self.place.timezone
        self.max_pages = max_pages or s.scraper_max_places_per_campaign * 2
        self.pages_opened = 0
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()
        # platform -> Playwright storage state of the user's linked account; one isolated context each.
        self.sessions = sessions or {}
        self._session_pages: dict[str, Any] = {}

    async def _ensure(self) -> Any:
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on image
            raise BrowserUnavailable("Playwright is not installed in this worker image") from exc
        s = get_settings()
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=s.scraper_headless, args=s.scraper_browser_args)
        except Exception as exc:  # noqa: BLE001 - missing browser binary etc.
            await self._pw.stop()
            raise BrowserUnavailable(f"Chromium could not start: {exc}") from exc
        self._context = await self._browser.new_context(**self._context_options())
        self._context.set_default_timeout(s.scraper_page_timeout_seconds * 1000)
        self._page = await self._context.new_page()
        return self._page

    async def _session_page(self, platform: str) -> Any:
        if platform in self._session_pages:
            return self._session_pages[platform]
        await self._ensure()
        ctx = await self._browser.new_context(**self._context_options(), storage_state=self.sessions[platform])
        ctx.set_default_timeout(get_settings().scraper_page_timeout_seconds * 1000)
        self._session_pages[platform] = await ctx.new_page()
        return self._session_pages[platform]

    def _context_options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "locale": self.locale,
            "timezone_id": self.timezone,
            "viewport": {"width": 1280, "height": 900},
            "extra_http_headers": {"Accept-Language": self.place.accept_language},
        }
        if self.place.lat or self.place.lon:
            opts["geolocation"] = {"latitude": self.place.lat, "longitude": self.place.lon}
            opts["permissions"] = ["geolocation"]
        return opts

    async def _pause(self) -> None:
        s = get_settings()
        await asyncio.sleep(random.uniform(s.scraper_delay_min, s.scraper_delay_max))

    async def open(self, url: str, wait_for: str | None = None, session: str | None = None) -> tuple[str, str]:
        """Navigate and return (final_url, html). Raises ScrapeBlocked on challenge pages.

        `session` names a platform whose linked account (if any) should be used for this page.
        """
        async with self._lock:
            if self.pages_opened >= self.max_pages:
                raise ScrapeBlocked(f"Page budget for this run reached ({self.max_pages} pages)")
            logged_in = bool(session and session in self.sessions)
            page = await (self._session_page(session) if logged_in else self._ensure())
            if self.pages_opened:
                await self._pause()
            self.pages_opened += 1
            await page.goto(url, wait_until="domcontentloaded")
            if logged_in:  # logged-in pages render client-side; give them a moment to settle
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:  # noqa: BLE001 - long-polling pages never go idle; use what rendered
                    log.debug("page did not go idle", extra={"url": url})
            if "consent." in page.url:
                await self._dismiss_consent(page)
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10_000)
                except Exception:  # noqa: BLE001 - absent selector is handled by the parser
                    log.debug("selector not found", extra={"url": url, "selector": wait_for})
            html = await page.content()
            if is_blocked(page.url, html):
                raise ScrapeBlocked("The site served a challenge/unusual-traffic page; stopping this source")
            return page.url, html

    async def _dismiss_consent(self, page: Any) -> None:
        for sel in MAPS["consent_reject"]:
            btn = await page.query_selector(sel)
            if btn is not None:
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")
                return

    async def scroll_feed(self, selector: str, max_rounds: int, stop_text: str | None = None) -> str:
        """Scroll an infinite list until it stops growing (or `stop_text` appears); return the page HTML."""
        async with self._lock:
            page = await self._ensure()
            previous = -1
            for _ in range(max_rounds):
                count = await page.evaluate(
                    """(sel) => { const f = document.querySelector(sel); if (!f) return -1;
                       f.scrollBy(0, f.scrollHeight); return f.querySelectorAll('a[href*="/maps/place/"]').length; }""",
                    selector,
                )
                if count < 0:
                    break
                await asyncio.sleep(random.uniform(1.2, 2.2))
                html = await page.content()
                if (stop_text and stop_text in html) or count == previous:
                    break
                previous = count
            return await page.content()

    async def close(self) -> None:
        for page in self._session_pages.values():
            try:
                await page.context.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                log.debug("session context cleanup failed")
        self._session_pages = {}
        for obj, method in ((self._context, "close"), (self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    await getattr(obj, method)()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    log.debug("browser cleanup failed")
        self._pw = self._browser = self._context = self._page = None
