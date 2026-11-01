import type { Metadata } from "next";

import { ForgotPasswordForm } from "@/features/auth/account-forms";

// The emailed links carry a token in the query string: keep these pages out of search and referrers.
export const metadata: Metadata = { title: "استعادة كلمة المرور", robots: { index: false }, referrer: "no-referrer" };

export default function Page() {
  return <ForgotPasswordForm />;
}
