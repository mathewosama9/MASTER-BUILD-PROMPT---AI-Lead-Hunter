"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, MailCheck, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";

import { AuthFrame } from "./auth-frame";

/** The token from the emailed link. It is removed from the address bar once read. */
function takeToken(): string | null {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  if (token) {
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search);
  }
  return token;
}

function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <AuthFrame>
      <h1 className="mb-6 text-2xl font-bold tracking-tight">{title}</h1>
      {children}
      <p className="mt-6 text-sm">
        <Link href="/login" className="text-muted-foreground hover:text-foreground">
          {t.account.backToLogin}
        </Link>
      </p>
    </AuthFrame>
  );
}

function Notice({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  const Icon = ok ? CheckCircle2 : XCircle;
  return (
    <p role={ok ? "status" : "alert"} className="flex gap-2 text-sm leading-relaxed">
      <Icon className={ok ? "mt-0.5 size-4 shrink-0 text-success" : "mt-0.5 size-4 shrink-0 text-destructive"} aria-hidden />
      <span>{children}</span>
    </p>
  );
}

function FormError({ message }: { message: string | null }) {
  return message ? (
    <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
      {message}
    </p>
  ) : null;
}

const forgotSchema = z.object({ email: z.email("invalidEmail") });

export function ForgotPasswordForm() {
  const { t, vmsg } = useI18n();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof forgotSchema>>({ resolver: zodResolver(forgotSchema), defaultValues: { email: "" } });

  async function onSubmit(values: z.infer<typeof forgotSchema>) {
    setError(null);
    try {
      await api("/auth/password/forgot", { method: "POST", body: values });
      setSent(true);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 429 ? t.account.tooMany : String((e as Error).message));
    }
  }

  return (
    <AuthCard title={t.account.forgotTitle}>
      {sent ? (
        <Notice ok>{t.account.forgotSent}</Notice>
      ) : (
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
          <p className="text-sm text-muted-foreground">{t.account.forgotHint}</p>
          <Field label={t.auth.email} htmlFor="email" error={vmsg(form.formState.errors.email?.message)}>
            <Input
              id="email"
              type="email"
              dir="ltr"
              autoComplete="email"
              aria-invalid={!!form.formState.errors.email}
              {...form.register("email")}
            />
          </Field>
          <FormError message={error} />
          <Button type="submit" variant="ink" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? <Spinner /> : null}
            {t.account.sendLink}
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

const resetSchema = z
  .object({ password: z.string().min(10, "passwordMin"), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "passwordMismatch" });

export function ResetPasswordForm() {
  const { t, vmsg } = useI18n();
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<"form" | "done" | "invalid">("form");
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof resetSchema>>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: "", confirm: "" },
  });

  useEffect(() => {
    const value = takeToken(); // reads the address bar, so only after mount
    /* eslint-disable react-hooks/set-state-in-effect */
    if (value) setToken(value);
    else setState("invalid");
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  async function onSubmit(values: z.infer<typeof resetSchema>) {
    setError(null);
    try {
      await api("/auth/password/reset", { method: "POST", body: { token, password: values.password } });
      setState("done");
    } catch (e) {
      if (e instanceof ApiError && e.code === "invalid_token") setState("invalid");
      else setError(String((e as Error).message));
    }
  }

  return (
    <AuthCard title={t.account.resetTitle}>
      {state === "done" ? (
        <div className="flex flex-col gap-4">
          <Notice ok>{t.account.resetDone}</Notice>
          <Button asChild variant="ink">
            <Link href="/login">{t.auth.submit}</Link>
          </Button>
        </div>
      ) : state === "invalid" ? (
        <div className="flex flex-col gap-4">
          <Notice ok={false}>{t.account.resetInvalid}</Notice>
          <Button asChild variant="ink">
            <Link href="/forgot-password">{t.account.requestNew}</Link>
          </Button>
        </div>
      ) : (
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
          <Field label={t.account.newPassword} htmlFor="password" error={vmsg(form.formState.errors.password?.message)}>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!form.formState.errors.password}
              {...form.register("password")}
            />
          </Field>
          <Field label={t.account.confirmPassword} htmlFor="confirm" error={vmsg(form.formState.errors.confirm?.message)}>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!form.formState.errors.confirm}
              {...form.register("confirm")}
            />
          </Field>
          <FormError message={error} />
          <Button type="submit" variant="ink" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? <Spinner /> : null}
            {t.account.savePassword}
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

export function VerifyEmail() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const started = useRef(false);
  const [state, setState] = useState<"checking" | "done" | "invalid" | "error">("checking");

  useEffect(() => {
    if (started.current) return; // the link works once per page load, even under StrictMode's double effects
    started.current = true;
    const token = takeToken();
    if (!token) {
      setState("invalid"); // eslint-disable-line react-hooks/set-state-in-effect
      return;
    }
    api("/auth/email/verify", { method: "POST", body: { token } })
      .then(() => {
        setState("done");
        void qc.invalidateQueries({ queryKey: ["me"] });
        void qc.invalidateQueries({ queryKey: ["billing-summary"] });
      })
      .catch((e) => setState(e instanceof ApiError && e.code === "invalid_token" ? "invalid" : "error"));
  }, [qc]);

  return (
    <AuthCard title={t.account.verifyTitle}>
      {state === "checking" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> {t.account.verifying}
        </p>
      ) : state === "done" ? (
        <div className="flex flex-col gap-4">
          <Notice ok>{t.account.verified}</Notice>
          <Button asChild variant="ink">
            <Link href="/app">{t.account.openDashboard}</Link>
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Notice ok={false}>{state === "invalid" ? t.account.verifyInvalid : t.account.verifyFailed}</Notice>
          <Button asChild variant="ink">
            <Link href="/app">{t.account.openDashboard}</Link>
          </Button>
        </div>
      )}
    </AuthCard>
  );
}

/** Dashboard strip until the user confirms their email, with a resend button. */
export function VerifyEmailBanner({ email, trialPending }: { email: string; trialPending: boolean }) {
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "sending" | "sent" | "limited">("idle");

  async function resend() {
    setState("sending");
    try {
      await api("/auth/email/resend", { method: "POST" });
      setState("sent");
    } catch (e) {
      setState(e instanceof ApiError && e.status === 429 ? "limited" : "idle");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rasd-500/30 bg-rasd-500/10 px-4 py-2 text-xs text-foreground md:px-6">
      <MailCheck className="size-4 text-rasd-500" aria-hidden />
      <span className="min-w-0 flex-1">{(trialPending ? t.account.bannerTrial : t.account.banner).replace("{email}", email)}</span>
      {state === "sent" ? (
        <span role="status" className="font-medium text-emerald-600 dark:text-emerald-400">
          {t.account.resent}
        </span>
      ) : state === "limited" ? (
        <span role="status" className="text-muted-foreground">
          {t.account.tooMany}
        </span>
      ) : (
        <Button size="sm" variant="outline" className="h-7" onClick={resend} disabled={state === "sending"}>
          {state === "sending" ? <Spinner /> : null}
          {t.account.resend}
        </Button>
      )}
    </div>
  );
}
