import type { Metadata } from "next";

import { ResetPasswordForm } from "@/features/auth/account-forms";

// The emailed links carry a token in the query string: keep these pages out of search and referrers.
export const metadata: Metadata = { title: "اختر كلمة مرور جديدة", robots: { index: false }, referrer: "no-referrer" };

export default function Page() {
  return <ResetPasswordForm />;
}
