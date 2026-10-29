import type { Metadata } from "next";

import { SuppressionPage } from "@/features/suppression/suppression";

export const metadata: Metadata = { title: "Suppression list" };

export default function Page() {
  return <SuppressionPage />;
}
