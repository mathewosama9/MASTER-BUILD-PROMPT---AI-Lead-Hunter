"""Login-browser service: a real (headed) Chromium the user drives from the dashboard to log in to a platform.

Runs in its own container (`login-browser`). For each login it starts a TigerVNC X server protected by a
one-time password, opens Chromium on the platform's login page, and noVNC (websockify on :6080) streams that
screen into the dashboard. The user types their own credentials and 2FA there; when they click "Save", the API
calls /capture and receives only the browser's cookies (Playwright storage state). Passwords never reach the API.

One login at a time; an idle login is torn down after LOGIN_TIMEOUT seconds.
Control endpoints are internal (Docker network) and require X-Internal-Token.

Run: uvicorn app.login_browser:app --host 0.0.0.0 --port 7900
"""

import asyncio
import hashlib
import logging
import os
import secrets
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings

log = logging.getLogger("login_browser")

DISPLAY = ":99"
XVNC = "/usr/bin/Xvnc"
VNCPASSWD = "/usr/bin/vncpasswd"
VNC_PORT = 5900
LOGIN_TIMEOUT = 15 * 60
LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "tiktok": "https://www.tiktok.com/login",
    "snapchat": "https://accounts.snapchat.com/accounts/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "facebook": "https://www.facebook.com/login",
}


def internal_token() -> str:
    """Shared secret for API <-> login-browser calls, derived from SECRET_KEY (present in both containers)."""
    return hashlib.sha256(f"login-browser:{get_settings().secret_key}".encode()).hexdigest()


class _State:
    platform: str | None = None
    login_id: str | None = None  # opaque id from the API; /capture and /cancel must present it
    started: float = 0.0
    xvnc: subprocess.Popen | None = None
    pw: Any = None
    browser: Any = None
    context: Any = None
    workdir: tempfile.TemporaryDirectory | None = None


state = _State()
lock = asyncio.Lock()


async def _teardown() -> None:
    for obj, method in ((state.context, "close"), (state.browser, "close"), (state.pw, "stop")):
        if obj is not None:
            try:
                await getattr(obj, method)()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                log.debug("cleanup step failed")
    if state.xvnc is not None:
        state.xvnc.terminate()
        try:
            state.xvnc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            state.xvnc.kill()
    # A display that died without cleanup leaves its lock/socket behind and blocks the next Xvnc on :99.
    for leftover in (f"/tmp/.X{DISPLAY[1:]}-lock", f"/tmp/.X11-unix/X{DISPLAY[1:]}"):  # noqa: S108 - X11 fixed paths
        try:
            os.remove(leftover)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("could not remove %s: %s", leftover, exc)
    if state.workdir is not None:
        state.workdir.cleanup()
    state.platform, state.login_id, state.xvnc, state.pw, state.browser, state.context, state.workdir = (None,) * 7


async def _watchdog() -> None:
    while True:
        await asyncio.sleep(30)
        if state.platform and time.time() - state.started > LOGIN_TIMEOUT:
            async with lock:
                log.info("login timed out", extra={"platform": state.platform})
                await _teardown()


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    task = asyncio.create_task(_watchdog())
    yield
    task.cancel()
    await _teardown()


app = FastAPI(title="Rasd login browser", lifespan=lifespan, docs_url=None, redoc_url=None)


def _auth(token: str | None) -> None:
    if not token or not secrets.compare_digest(token, internal_token()):
        raise HTTPException(status_code=401, detail="bad internal token")


class StartIn(BaseModel):
    platform: str
    login_id: str


class LoginRef(BaseModel):
    login_id: str


def _check_login(login_id: str) -> None:
    if not state.platform or state.context is None or state.login_id is None:
        raise HTTPException(status_code=409, detail="no login in progress")
    if not secrets.compare_digest(login_id, state.login_id):
        raise HTTPException(status_code=409, detail="this login was replaced or has ended")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "busy": state.platform}


@app.post("/start")
async def start(body: StartIn, x_internal_token: str | None = Header(default=None)) -> dict:
    _auth(x_internal_token)
    if body.platform not in LOGIN_URLS:
        raise HTTPException(status_code=400, detail="unsupported platform")
    async with lock:
        await _teardown()  # one login at a time: a new start replaces any previous one (and clears stale locks)
        password = secrets.token_urlsafe(6)[:8]  # VNC passwords are limited to 8 characters
        state.workdir = tempfile.TemporaryDirectory()
        passwd_file = os.path.join(state.workdir.name, "passwd")
        with open(passwd_file, "wb") as fh:  # fixed argv, no shell; the password is generated here
            subprocess.run([VNCPASSWD, "-f"], input=password.encode(), stdout=fh, check=True)  # noqa: S603
        os.chmod(passwd_file, 0o600)
        state.xvnc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                XVNC,
                DISPLAY,
                "-geometry",
                "1280x860",
                "-depth",
                "24",
                "-rfbport",
                str(VNC_PORT),
                "-SecurityTypes",
                "VncAuth",
                "-rfbauth",
                passwd_file,
                "-localhost",
                "yes",
                "-AlwaysShared",
            ],
            stdout=subprocess.DEVNULL,
            stderr=open(os.path.join(state.workdir.name, "xvnc.log"), "wb"),  # noqa: SIM115 - closed with workdir
        )
        await asyncio.sleep(1.0)
        if state.xvnc.poll() is not None:
            err = open(os.path.join(state.workdir.name, "xvnc.log"), encoding="utf-8", errors="replace").read()
            log.error("Xvnc exited: %s", err[-800:])
            await _teardown()
            raise HTTPException(status_code=500, detail=f"VNC display failed to start: {err[-300:]}")
        from playwright.async_api import async_playwright

        state.pw = await async_playwright().start()
        state.browser = await state.pw.chromium.launch(
            headless=False,
            env={**os.environ, "DISPLAY": DISPLAY},
            args=["--window-position=0,0", "--window-size=1280,860", "--no-first-run", "--disable-dev-shm-usage"],
        )
        state.context = await state.browser.new_context(no_viewport=True)
        page = await state.context.new_page()
        await page.goto(LOGIN_URLS[body.platform], wait_until="domcontentloaded")
        state.platform, state.login_id, state.started = body.platform, body.login_id, time.time()
        return {"platform": body.platform, "vnc_password": password}


@app.post("/capture")
async def capture(body: LoginRef, x_internal_token: str | None = Header(default=None)) -> dict:
    _auth(x_internal_token)
    async with lock:
        _check_login(body.login_id)
        # The browser stays open: if the API rejects the cookies (login not finished) the user can continue.
        # The API calls /cancel after a successful save.
        return {"platform": state.platform, "storage_state": await state.context.storage_state()}


@app.post("/cancel")
async def cancel(body: LoginRef, x_internal_token: str | None = Header(default=None)) -> dict:
    _auth(x_internal_token)
    async with lock:
        if state.platform is not None:  # nothing open: cancelling is a no-op
            _check_login(body.login_id)
        await _teardown()
    return {"status": "cancelled"}
