import { PricingPage } from "@/features/site/pricing";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/pricing", ar.pricing.metaTitle, ar.pricing.metaDescription);

export default function Page() {
  return <PricingPage />;
}
