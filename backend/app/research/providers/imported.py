"""Uploaded CSV/XLSX lists. Rows are parsed and validated at upload (`services/imports.py`); here they only
become candidates, which the pipeline then enriches, analyses and scores like any other source."""

import json
import logging

from app.models.enums import ProviderStatus
from app.research.enrichment.normalize import homepage_url
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderInfo,
    ProviderState,
    SearchQuery,
)

log = logging.getLogger(__name__)


class ImportProvider:
    info = ProviderInfo(
        key="import",
        name="File import (CSV/Excel)",
        kind="discovery",
        description="Your own list (exhibitors, chambers of commerce...). Columns: name, website, phone, email, "
        "city, instagram, facebook, snapchat, tiktok, linkedin. English or Arabic headers.",
        requires=[],
    )

    def state(self, ctx: ProviderContext) -> ProviderState:
        return ProviderState(ProviderStatus.CONNECTED, "Upload a CSV or Excel file in the campaign wizard.")

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        out: list[BusinessCandidate] = []
        for entry in query.manual_urls:
            try:
                row = json.loads(entry)
            except ValueError:
                log.info("skipping non-JSON import row")
                continue
            if not isinstance(row, dict) or not row.get("name"):
                continue
            website = row.get("website")
            socials = list(row.get("social_urls") or [])
            out.append(
                BusinessCandidate(
                    name=str(row["name"])[:300],
                    website_url=homepage_url(website) if website else None,
                    industry=query.industry,
                    country=query.country,
                    city=row.get("city") or query.city,
                    address=row.get("address"),
                    phone=row.get("phone"),
                    email=row.get("email"),
                    source_provider=self.info.key,
                    source_url=(website or (socials[0] if socials else f"import:line-{row.get('line', len(out))}"))[
                        :1000
                    ],
                    source_title="Imported list",
                    social_urls=socials,
                    identifiers={"social": socials[0].lower()} if socials else {},
                    raw={"import_line": row.get("line")},
                )
            )
        return out

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        return self.state(ctx)
