import { Suspense } from "react";

import { LoadingState } from "@/components/ui/states";
import { CampaignMonitor } from "@/features/campaigns/campaign-monitor";

// Params are awaited inside <Suspense> so the static shell can prerender (Cache Components).
export default function CampaignPage({ params }: PageProps<"/app/campaigns/[id]">) {
  return (
    <Suspense fallback={<LoadingState rows={6} />}>
      <Monitor params={params} />
    </Suspense>
  );
}

async function Monitor({ params }: Pick<PageProps<"/app/campaigns/[id]">, "params">) {
  const { id } = await params;
  return <CampaignMonitor id={id} />;
}
