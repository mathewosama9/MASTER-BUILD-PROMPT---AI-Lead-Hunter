import { Suspense } from "react";

import { LoadingState } from "@/components/ui/states";
import { LeadDetailView } from "@/features/leads/lead-detail";

export default function LeadPage({ params }: PageProps<"/leads/[id]">) {
  return (
    <Suspense fallback={<LoadingState rows={8} />}>
      <Detail params={params} />
    </Suspense>
  );
}

async function Detail({ params }: Pick<PageProps<"/leads/[id]">, "params">) {
  const { id } = await params;
  return <LeadDetailView id={id} />;
}
