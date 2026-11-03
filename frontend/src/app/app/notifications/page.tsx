import type { Metadata } from "next";

import { NotificationsPage } from "@/features/notifications/notifications-page";
import { dictionaries } from "@/i18n/dictionaries";

export const metadata: Metadata = { title: dictionaries.ar.notify.pageTitle };

export default function Page() {
  return <NotificationsPage />;
}
