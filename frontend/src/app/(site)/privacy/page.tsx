import { LegalPage } from "@/features/site/legal";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/privacy", `${ar.legal.privacyTitle} | رصد`, ar.legal.privacyMeta);

export default function Page() {
  return <LegalPage kind="privacy" />;
}
