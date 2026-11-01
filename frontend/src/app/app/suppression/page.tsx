import type { Metadata } from "next";

import { SuppressionPage } from "@/features/suppression/suppression";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.suppression };

export default function Page() {
  return <SuppressionPage />;
}
