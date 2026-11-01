import type { Metadata } from "next";

import { CampaignWizard } from "@/features/campaigns/wizard";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.newCampaign };

export default function NewCampaignPage() {
  return <CampaignWizard />;
}
