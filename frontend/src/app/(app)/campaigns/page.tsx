import type { Metadata } from "next";

import { CampaignList } from "@/features/campaigns/campaign-list";

export const metadata: Metadata = { title: "Campaigns" };

export default function CampaignsPage() {
  return <CampaignList />;
}
