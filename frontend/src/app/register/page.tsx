import type { Metadata } from "next";

import { RegisterForm } from "@/features/auth/register-form";

export const metadata: Metadata = { title: "ابدأ تجربتك المجانية" };

export default function RegisterPage() {
  return <RegisterForm />;
}
