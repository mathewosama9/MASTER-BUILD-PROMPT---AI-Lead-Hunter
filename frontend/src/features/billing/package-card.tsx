"use client";

import { useI18n } from "@/i18n/provider";
import { cn, formatNumber, formatPrice } from "@/lib/utils";
import type { CreditPackage } from "@/types/api";

/** Index of the package to highlight: the admin's featured one, else the middle of three or more. */
export function popularIndex(packages: CreditPackage[]): number {
  const featured = packages.findIndex((p) => p.featured);
  if (featured >= 0) return featured;
  return packages.length >= 3 ? Math.floor(packages.length / 2) : -1;
}

/** One credit package, shared by the public pricing page and the in-app billing page. */
export function PackageCard({
  pkg,
  hot,
  selected,
  compact,
  children,
}: {
  pkg: CreditPackage;
  hot?: boolean;
  selected?: boolean;
  compact?: boolean;
  children?: React.ReactNode;
}) {
  const { t, locale } = useI18n();
  const p = t.site.pricing;
  const per = Number(pkg.price) / Math.max(pkg.credits, 1);
  return (
    <div
      className={cn(
        "relative flex h-full flex-col rounded-2xl border",
        compact ? "p-5" : "p-7",
        hot ? "border-ink-900 bg-ink-900 text-paper shadow-2xl shadow-ink-900/20" : "bg-card",
        selected && "ring-4 ring-signal-400/60",
      )}
    >
      {hot ? (
        <span className="absolute -top-3 start-6 rounded-full bg-signal-400 px-3 py-1 text-xs font-semibold text-ink-900">
          {p.popular}
        </span>
      ) : null}
      <p className={cn("font-display font-semibold", compact ? "text-base" : "text-lg")}>{locale === "ar" ? pkg.name_ar : pkg.name_en}</p>
      <p className={cn("font-display font-bold tabular-nums tracking-tight", compact ? "mt-3 text-3xl" : "mt-5 text-5xl")}>
        {formatPrice(pkg.price, pkg.currency)}
      </p>
      <p className={cn("mt-2 text-sm tabular-nums", hot ? "text-mist-300" : "text-muted-foreground")}>
        {formatNumber(pkg.credits, locale)} {p.credits} ·{" "}
        {p.perContact.replace("{price}", formatPrice(Math.round(per * 100) / 100, pkg.currency))}
      </p>
      {children ? <div className={cn("mt-auto", compact ? "pt-5" : "pt-7")}>{children}</div> : null}
    </div>
  );
}
