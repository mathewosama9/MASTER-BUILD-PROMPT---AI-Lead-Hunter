import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/ui/states";
import { LeadsPage } from "@/features/leads/leads-page";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.leads };

export default function Page() {
  return (
    <Suspense fallback={<LoadingState rows={8} />}>
      <LeadsPage />
    </Suspense>
  );
}
