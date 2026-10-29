import type { Metadata } from "next";

import { CampaignWizard } from "@/features/campaigns/wizard";

export const metadata: Metadata = { title: "New campaign" };

export default function NewCampaignPage() {
  return <CampaignWizard />;
}
