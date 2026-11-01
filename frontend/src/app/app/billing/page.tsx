import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/ui/states";
import { BillingPage } from "@/features/billing/billing";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.billing };

// The billing page reads ?pkg= from the pricing page, which needs a Suspense boundary.
export default function Page() {
  return (
    <Suspense fallback={<LoadingState />}>
      <BillingPage />
    </Suspense>
  );
}
