import type { Metadata } from "next";

import { Unsubscribe } from "@/features/auth/account-forms";

// The emailed link carries a token in the query string: keep this page out of search and referrers.
export const metadata: Metadata = { title: "إلغاء الاشتراك", robots: { index: false }, referrer: "no-referrer" };

export default function Page() {
  return <Unsubscribe />;
}
