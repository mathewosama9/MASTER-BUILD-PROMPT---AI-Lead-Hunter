import type { Metadata } from "next";

import { SettingsPage } from "@/features/settings/settings";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.nav.settings };

export default function Page() {
  return <SettingsPage />;
}
