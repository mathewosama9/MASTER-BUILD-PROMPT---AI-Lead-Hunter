import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/ui/states";
import { LeadsPage } from "@/features/leads/leads-page";

export const metadata: Metadata = { title: "Leads" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingState rows={8} />}>
      <LeadsPage />
    </Suspense>
  );
}
