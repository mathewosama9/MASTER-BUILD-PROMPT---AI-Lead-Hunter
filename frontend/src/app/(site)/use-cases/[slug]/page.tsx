import { notFound } from "next/navigation";

import { UseCaseDetailPage } from "@/features/site/use-cases";
import { ar, pageMetadata, USE_CASE_SLUGS } from "@/lib/site";

export function generateStaticParams() {
  return USE_CASE_SLUGS.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: PageProps<"/use-cases/[slug]">) {
  const { slug } = await params;
  const item = ar.useCases.items.find((x) => x.key === slug);
  if (!item) return {};
  return pageMetadata(`/use-cases/${slug}`, `${item.title} · رصد`, `${item.pain} ${item.short}`);
}

export default async function Page({ params }: PageProps<"/use-cases/[slug]">) {
  const { slug } = await params;
  if (!USE_CASE_SLUGS.includes(slug)) notFound();
  return <UseCaseDetailPage slug={slug} />;
}
