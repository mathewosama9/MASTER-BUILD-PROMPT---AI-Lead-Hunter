"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { LogoMark } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";

export const loginSchema = z.object({
  email: z.email("invalidEmail"),
  password: z.string().min(1, "required"),
});
type LoginValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { t, locale, setLocale, vmsg } = useI18n();
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });

  async function onSubmit(values: LoginValues) {
    setError(null);
    try {
      await api("/auth/login", { method: "POST", body: values });
      await qc.invalidateQueries({ queryKey: ["me"] });
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? t.auth.invalid : String((e as Error).message));
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-navy-900 p-4">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 end-[-10rem] size-[32rem] rounded-full bg-brand-500/25 blur-3xl"
      />
      <div aria-hidden className="pointer-events-none absolute -bottom-40 start-[-8rem] size-[26rem] rounded-full bg-sun-500/10 blur-3xl" />
      <div className="relative w-full max-w-sm rounded-xl border border-white/10 bg-navy-800/70 p-8 text-ghost-50 shadow-2xl backdrop-blur">
        <div className="mb-8 flex items-center gap-3">
          <LogoMark className="size-11" />
          <div>
            <p className="text-lg font-bold tracking-tight">{t.appName}</p>
            <p className="text-xs text-lavender-300">{t.tagline}</p>
          </div>
        </div>
        <h1 className="mb-5 text-sm font-medium text-lavender-300">{t.auth.title}</h1>
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
          <Field label={t.auth.email} htmlFor="email" error={vmsg(form.formState.errors.email?.message)}>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              className="border-white/15 bg-navy-900 text-ghost-50"
              aria-invalid={!!form.formState.errors.email}
              {...form.register("email")}
            />
          </Field>
          <Field label={t.auth.password} htmlFor="password" error={vmsg(form.formState.errors.password?.message)}>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              className="border-white/15 bg-navy-900 text-ghost-50"
              aria-invalid={!!form.formState.errors.password}
              {...form.register("password")}
            />
          </Field>
          {error ? (
            <p role="alert" className="rounded-md bg-rose-500/15 px-3 py-2 text-xs text-rose-200">
              {error}
            </p>
          ) : null}
          <Button type="submit" variant="accent" disabled={form.formState.isSubmitting} className="mt-2">
            {form.formState.isSubmitting ? <Spinner /> : null}
            {t.auth.submit}
          </Button>
        </form>
        <button
          type="button"
          onClick={() => setLocale(locale === "en" ? "ar" : "en")}
          className="mt-6 text-xs text-lavender-300 hover:text-ghost-50"
        >
          {locale === "en" ? "العربية" : "English"}
        </button>
      </div>
    </div>
  );
}
