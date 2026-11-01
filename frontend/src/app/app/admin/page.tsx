import type { Metadata } from "next";

import { AdminPage } from "@/features/admin/admin";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.admin };

export default function Page() {
  return <AdminPage />;
}
