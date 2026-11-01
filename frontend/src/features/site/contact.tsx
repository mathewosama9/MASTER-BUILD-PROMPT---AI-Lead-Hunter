"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Clock } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";

import { PageHero } from "./parts";

const INTERESTS = ["demo", "sales", "support", "partnership", "other"] as const;

export const contactSchema = z.object({
  name: z.string().trim().min(2, "required"),
  company: z.string().trim().max(200).optional(),
  email: z.email("invalidEmail"),
  phone: z
    .string()
    .trim()
    .refine((v) => v === "" || /^\+?[0-9 ()-]{7,32}$/.test(v), "invalidPhone")
    .optional(),
  interest: z.enum(INTERESTS),
  message: z.string().trim().max(3000).optional(),
  website: z.string().optional(), // honeypot
});
type ContactValues = z.infer<typeof contactSchema>;

export function ContactPage() {
  const { t, locale, vmsg } = useI18n();
  const c = t.site.contact;
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<ContactValues>({
    resolver: zodResolver(contactSchema),
    defaultValues: {
      name: "",
      company: "",
      email: "",
      phone: "",
      interest: "demo",
      message: "",
      website: "",
    },
  });

  async function onSubmit(values: ContactValues) {
    setError(null);
    try {
      await api("/public/contact", {
        method: "POST",
        body: { ...values, locale },
      });
      setSent(true);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 429 ? c.tooMany : String((e as Error).message));
    }
  }

  return (
    <>
      <PageHero eyebrow={c.eyebrow} title={c.title} subtitle={c.subtitle} />
      <section className="px-4 pb-20 md:px-6 md:pb-28">
        <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[1fr_2fr]">
          <aside className="h-fit rounded-2xl bg-ink-900 p-6 text-paper md:p-8">
            <p className="flex items-center gap-2 font-display text-lg font-semibold">
              <Clock className="size-5 text-signal-400" aria-hidden /> {c.asideTitle}
            </p>
            <ul className="mt-5 space-y-3 text-sm leading-relaxed text-mist-300">
              {c.aside.map((x) => (
                <li key={x} className="flex gap-2.5">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-signal-400" aria-hidden /> {x}
                </li>
              ))}
            </ul>
          </aside>
          <div className="rounded-2xl border bg-card p-6 md:p-8">
            {sent ? (
              <div role="status" className="flex flex-col items-center gap-3 py-8 text-center">
                <CheckCircle2 className="size-12 text-rasd-600" aria-hidden />
                <p className="text-lg font-semibold">{c.sentTitle}</p>
                <p className="text-muted-foreground">{c.sentBody}</p>
              </div>
            ) : (
              <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-5 md:grid-cols-2" noValidate>
                <Field label={c.name} htmlFor="c_name" error={vmsg(form.formState.errors.name?.message)}>
                  <Input id="c_name" autoComplete="name" {...form.register("name")} />
                </Field>
                <Field label={c.company} htmlFor="c_company">
                  <Input id="c_company" autoComplete="organization" {...form.register("company")} />
                </Field>
                <Field label={c.email} htmlFor="c_email" error={vmsg(form.formState.errors.email?.message)}>
                  <Input id="c_email" type="email" dir="ltr" autoComplete="email" {...form.register("email")} />
                </Field>
                <Field label={c.phone} htmlFor="c_phone" error={vmsg(form.formState.errors.phone?.message)}>
                  <Input id="c_phone" type="tel" dir="ltr" autoComplete="tel" {...form.register("phone")} />
                </Field>
                <Field label={c.interest} htmlFor="c_interest" className="md:col-span-2">
                  <Select id="c_interest" {...form.register("interest")}>
                    {INTERESTS.map((k) => (
                      <option key={k} value={k}>
                        {c.interests[k]}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={c.message} htmlFor="c_message" className="md:col-span-2">
                  <Textarea id="c_message" rows={5} {...form.register("message")} />
                </Field>
                {/* Honeypot: hidden from people and assistive tech; bots fill it. */}
                <div aria-hidden className="absolute -start-[9999px] h-0 w-0 overflow-hidden">
                  <label htmlFor="c_website">Website</label>
                  <input id="c_website" tabIndex={-1} autoComplete="off" {...form.register("website")} />
                </div>
                {error ? (
                  <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive md:col-span-2">
                    {error}
                  </p>
                ) : null}
                <div className="md:col-span-2">
                  <Button type="submit" size="lg" disabled={form.formState.isSubmitting}>
                    {form.formState.isSubmitting ? <Spinner /> : null} {c.submit}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
