"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";

import { AuthFrame } from "./auth-frame";

export const registerSchema = z.object({
  full_name: z.string().trim().min(2, "required"),
  company: z.string().trim().min(2, "required"),
  email: z.email("invalidEmail"),
  phone: z
    .string()
    .trim()
    .regex(/^\+?[0-9 ()-]{7,32}$/, "invalidPhone")
    .refine((v) => {
      const digits = v.replace(/\D/g, "").length;
      return digits >= 7 && digits <= 15;
    }, "invalidPhone"),
  password: z.string().min(10, "passwordMin"),
});
type RegisterValues = z.infer<typeof registerSchema>;

interface TrialTerms {
  trial_days: number;
  trial_credits: number;
}

const fields: { name: keyof RegisterValues; type: string; autoComplete: string }[] = [
  { name: "full_name", type: "text", autoComplete: "name" },
  { name: "company", type: "text", autoComplete: "organization" },
  { name: "email", type: "email", autoComplete: "email" },
  { name: "phone", type: "tel", autoComplete: "tel" },
  { name: "password", type: "password", autoComplete: "new-password" },
];

export function RegisterForm() {
  const { t, locale, vmsg } = useI18n();
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const trial = useQuery({ queryKey: ["public-trial"], queryFn: () => api<TrialTerms>("/public/trial") });
  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { full_name: "", company: "", email: "", phone: "", password: "" },
  });

  async function onSubmit(values: RegisterValues) {
    setError(null);
    try {
      await api("/auth/register", { method: "POST", body: { ...values, locale } });
      await qc.invalidateQueries({ queryKey: ["me"] });
      // Straight into onboarding; a business type picked on the public site rides along.
      const category = new URLSearchParams(window.location.search).get("category");
      router.replace(category ? `/app/welcome?category=${encodeURIComponent(category)}` : "/app/welcome");
    } catch (e) {
      if (e instanceof ApiError && e.code === "email_taken") setError(t.register.emailTaken);
      else if (e instanceof ApiError && e.status === 429) setError(t.register.tooMany);
      else setError(String((e as Error).message));
    }
  }

  return (
    <AuthFrame wide>
      <h1 className="text-2xl font-bold tracking-tight">{t.register.title}</h1>
      {trial.data ? (
        <p className="mb-6 mt-2 inline-flex rounded-full bg-signal-100 px-3 py-1 text-sm font-medium text-rasd-800 dark:bg-signal-400/10 dark:text-signal-300">
          {t.register.trialOffer.replace("{days}", String(trial.data.trial_days)).replace("{credits}", String(trial.data.trial_credits))}
        </p>
      ) : (
        <div className="mb-6" />
      )}
      <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        {fields.map((f) => (
          <Field key={f.name} label={t.register[f.name]} htmlFor={f.name} error={vmsg(form.formState.errors[f.name]?.message)}>
            <div className="relative">
              <Input
                id={f.name}
                type={f.name === "password" && showPassword ? "text" : f.type}
                autoComplete={f.autoComplete}
                dir={f.type === "email" || f.type === "tel" || f.type === "password" ? "ltr" : undefined}
                className={f.name === "password" ? "pe-11" : undefined}
                aria-invalid={!!form.formState.errors[f.name]}
                {...form.register(f.name)}
              />
              {f.name === "password" ? (
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? t.register.hidePassword : t.register.showPassword}
                  aria-pressed={showPassword}
                  className="absolute inset-y-0 end-0 flex w-11 items-center justify-center rounded-e-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                </button>
              ) : null}
            </div>
          </Field>
        ))}
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" variant="ink" size="lg" disabled={form.formState.isSubmitting} className="mt-2">
          {form.formState.isSubmitting ? <Spinner /> : null}
          {t.register.submit}
        </Button>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {t.register.consentPrefix}{" "}
          <Link href="/terms" target="_blank" className="font-medium text-primary underline-offset-2 hover:underline">
            {t.register.terms}
          </Link>{" "}
          {t.register.consentAnd}
          <Link href="/privacy" target="_blank" className="font-medium text-primary underline-offset-2 hover:underline">
            {t.register.privacy}
          </Link>
          {t.register.consentSuffix}
        </p>
        {trial.data ? (
          <p className="text-xs text-muted-foreground">{t.register.verifyNote.replace("{credits}", String(trial.data.trial_credits))}</p>
        ) : null}
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        <Link href="/login" className="font-medium text-primary hover:underline">
          {t.register.haveAccount}
        </Link>
      </p>
    </AuthFrame>
  );
}
