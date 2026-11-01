import { HowItWorksPage } from "@/features/site/how-it-works";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/how-it-works", ar.how.metaTitle, ar.how.metaDescription);

export default function Page() {
  return <HowItWorksPage />;
}
