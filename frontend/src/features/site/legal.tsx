"use client";

import { useI18n } from "@/i18n/provider";

export function LegalPage({ kind }: { kind: "privacy" | "terms" }) {
  const { t } = useI18n();
  const l = t.site.legal;
  const title = kind === "privacy" ? l.privacyTitle : l.termsTitle;
  const sections = kind === "privacy" ? l.privacy : l.terms;
  return (
    <article className="px-4 py-16 md:px-6 md:py-24">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-4xl font-bold tracking-tight md:text-5xl">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{l.updated}</p>
        <div className="mt-12 space-y-10 border-t pt-10">
          {sections.map((s) => (
            <section key={s.h}>
              <h2 className="text-lg font-semibold">{s.h}</h2>
              <p className="mt-2 leading-relaxed text-foreground/85">{s.p}</p>
            </section>
          ))}
        </div>
      </div>
    </article>
  );
}
