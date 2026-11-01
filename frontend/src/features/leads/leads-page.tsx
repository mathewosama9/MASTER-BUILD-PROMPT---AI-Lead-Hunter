"use client";

import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/layout/app-shell";
import { useI18n } from "@/i18n/provider";

import { LeadsTable } from "./leads-table";

export function LeadsPage() {
  const { t } = useI18n();
  const params = useSearchParams();
  const campaignId = params.get("campaign_id") ?? undefined;
  const crmStatus = params.get("crm_status") ?? "";
  return (
    <div>
      <PageHeader title={t.leads.title} subtitle={t.leads.subtitle} />
      <LeadsTable key={`${campaignId ?? "all"}:${crmStatus}`} campaignId={campaignId} crmStatus={crmStatus} />
    </div>
  );
}
