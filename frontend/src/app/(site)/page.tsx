import { HomePage } from "@/features/site/home";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/", ar.home.metaTitle, ar.home.metaDescription);

export default function Page() {
  return <HomePage />;
}
