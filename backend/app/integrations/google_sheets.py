"""Minimal Google Sheets export using a service account (no Google SDK dependency).

Configure GOOGLE_SHEETS_CREDENTIALS_JSON (service-account JSON). The new spreadsheet is created in the service
account's Drive and optionally shared with `share_with` (the user's email) as writer.
"""

import json
import time

import httpx
import jwt

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
SCOPES = "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file"


class SheetsError(Exception):
    pass


async def _access_token(client: httpx.AsyncClient, creds: dict) -> str:
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": creds["client_email"],
            "scope": SCOPES,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        creds["private_key"],
        algorithm="RS256",
    )
    resp = await client.post(
        TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    )
    if resp.status_code >= 400:
        raise SheetsError(f"Google auth failed: {resp.text[:200]}")
    return resp.json()["access_token"]


async def export_to_sheet(
    credentials_json: str, title: str, header: list[str], rows: list[list], share_with: str | None = None
) -> str:
    try:
        creds = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise SheetsError("Invalid service-account JSON") from exc
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await _access_token(client, creds)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "https://sheets.googleapis.com/v4/spreadsheets", headers=headers, json={"properties": {"title": title}}
        )
        if resp.status_code >= 400:
            raise SheetsError(f"Could not create spreadsheet: {resp.text[:200]}")
        sheet = resp.json()
        sid = sheet["spreadsheetId"]
        values = [header] + [["" if v is None else v for v in r] for r in rows]
        resp = await client.put(
            f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/A1",
            params={"valueInputOption": "RAW"},
            headers=headers,
            json={"values": values},
        )
        if resp.status_code >= 400:
            raise SheetsError(f"Could not write values: {resp.text[:200]}")
        if share_with:
            await client.post(
                f"https://www.googleapis.com/drive/v3/files/{sid}/permissions",
                headers=headers,
                json={"type": "user", "role": "writer", "emailAddress": share_with},
            )
        return sheet.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{sid}"
