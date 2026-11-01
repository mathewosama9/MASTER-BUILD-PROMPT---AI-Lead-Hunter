"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
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
import { safeNextPath } from "@/lib/utils";

import { AuthFrame } from "./auth-frame";

export const loginSchema = z.object({
  email: z.email("invalidEmail"),
  password: z.string().min(1, "required"),
});
type LoginValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { t, vmsg } = useI18n();
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
      router.replace(safeNextPath(next, window.location.origin, "/app"));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? t.auth.invalid : String((e as Error).message));
    }
  }

  return (
    <AuthFrame>
      <h1 className="text-2xl font-bold tracking-tight">{t.auth.title}</h1>
      <p className="mb-8 mt-2 text-sm text-muted-foreground">{t.tagline}</p>
      <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <Field label={t.auth.email} htmlFor="email" error={vmsg(form.formState.errors.email?.message)}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!form.formState.errors.email} {...form.register("email")} />
        </Field>
        <Field label={t.auth.password} htmlFor="password" error={vmsg(form.formState.errors.password?.message)}>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            aria-invalid={!!form.formState.errors.password}
            {...form.register("password")}
          />
        </Field>
        <Link href="/forgot-password" className="-mt-2 self-end text-xs text-muted-foreground hover:text-foreground">
          {t.auth.forgot}
        </Link>
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" variant="ink" size="lg" disabled={form.formState.isSubmitting} className="mt-2">
          {form.formState.isSubmitting ? <Spinner /> : null}
          {t.auth.submit}
        </Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        {t.auth.noAccount}{" "}
        <Link href="/register" className="font-medium text-primary hover:underline">
          {t.auth.startTrial}
        </Link>
      </p>
    </AuthFrame>
  );
}
