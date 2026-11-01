import { LegalPage } from "@/features/site/legal";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/terms", `${ar.legal.termsTitle} | رصد`, ar.legal.termsMeta);

export default function Page() {
  return <LegalPage kind="terms" />;
}
