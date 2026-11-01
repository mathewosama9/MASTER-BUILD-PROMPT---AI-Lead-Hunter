import type { Metadata } from "next";

import { VerifyEmail } from "@/features/auth/account-forms";

// The emailed links carry a token in the query string: keep these pages out of search and referrers.
export const metadata: Metadata = { title: "تأكيد البريد الإلكتروني", robots: { index: false }, referrer: "no-referrer" };

export default function Page() {
  return <VerifyEmail />;
}
