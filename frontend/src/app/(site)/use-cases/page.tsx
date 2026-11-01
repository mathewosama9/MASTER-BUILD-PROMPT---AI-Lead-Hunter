import { UseCasesPage } from "@/features/site/use-cases";
import { ar, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata("/use-cases", ar.useCases.metaTitle, ar.useCases.metaDescription);

export default function Page() {
  return <UseCasesPage />;
}
