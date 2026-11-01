import type { Metadata } from "next";

import { CampaignList } from "@/features/campaigns/campaign-list";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.campaigns };

export default function CampaignsPage() {
  return <CampaignList />;
}
