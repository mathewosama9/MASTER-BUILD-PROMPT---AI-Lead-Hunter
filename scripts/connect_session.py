"""Link a social account (use a secondary account, not your personal one) to Rasd.

Opens a normal browser window on the platform's login page. You log in by hand (2FA works as usual).
When you press Enter here, only the session cookies are sent to your Rasd API, where they are stored
encrypted. Your password never leaves the browser.

Usage (from the project root, using the backend virtualenv which already has Playwright):
    backend/.venv/Scripts/python scripts/connect_session.py linkedin
    backend/.venv/Scripts/python scripts/connect_session.py tiktok --api http://localhost:8000
Platforms: linkedin, tiktok, snapchat, instagram, facebook
"""

import argparse
import asyncio
import getpass
import sys

import httpx

LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "tiktok": "https://www.tiktok.com/login",
    "snapchat": "https://accounts.snapchat.com/accounts/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "facebook": "https://www.facebook.com/login",
}


def api_login(api: str, email: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=api.rstrip("/") + "/api/v1", timeout=30)
    r = client.post("/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        sys.exit(f"Rasd login failed ({r.status_code}): {r.text[:200]}")
    client.headers["x-csrf-token"] = r.json()["csrf_token"]
    return client


async def capture(platform: str) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        await page.goto(LOGIN_URLS[platform])
        print(f"\nA browser window opened on the {platform} login page.")
        print("Log in completely (finish any 2FA), wait until your feed/home page shows, then come back here.")
        await asyncio.get_running_loop().run_in_executor(None, input, "Press Enter once you are logged in... ")
        state = await context.storage_state()
        await browser.close()
        return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("platform", choices=sorted(LOGIN_URLS))
    parser.add_argument("--api", default="http://localhost:8000", help="Rasd API base URL")
    parser.add_argument("--email", help="your Rasd admin email")
    args = parser.parse_args()

    email = args.email or input("Rasd admin email: ").strip()
    client = api_login(args.api, email, getpass.getpass("Rasd password: "))
    state = asyncio.run(capture(args.platform))
    r = client.post(f"/providers/sessions/{args.platform}", json={"storage_state": state})
    if r.status_code != 200:
        sys.exit(f"Saving the session failed ({r.status_code}): {r.text[:300]}")
    info = r.json()
    print(f"\n{args.platform} linked: status={info['status']}, daily page limit={info['daily_limit']}.")
    print("Disconnect any time in Settings → Integrations → Linked accounts.")


if __name__ == "__main__":
    main()
