"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  FlaskConical,
  Languages,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Plus,
  Radar,
  Settings,
  Sun,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Suspense, useEffect, useState, useSyncExternalStore } from "react";

const noopSubscribe = () => () => {};

import { DemoBadge } from "@/components/badges";
import { LogoMark } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/states";
import { useMe } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", key: "overview", icon: LayoutDashboard },
  { href: "/campaigns", key: "campaigns", icon: Radar },
  { href: "/leads", key: "leads", icon: Users },
  { href: "/suppression", key: "suppression", icon: Ban },
  { href: "/settings", key: "settings", icon: Settings },
] as const;

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { t } = useI18n();
  return (
    <nav className="flex flex-col gap-1" aria-label={t.common.mainNav}>
      {NAV.map(({ href, key, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-muted transition-colors hover:bg-white/5 hover:text-sidebar-foreground",
              active && "bg-brand-500/15 text-sidebar-foreground shadow-[inset_3px_0_0_var(--color-sun-500)] rtl:shadow-[inset_-3px_0_0_var(--color-sun-500)]",
            )}
          >
            <Icon className={cn("size-4", active ? "text-sun-500" : "text-sidebar-muted group-hover:text-brand-400")} />
            {t.nav[key]}
          </Link>
        );
      })}
    </nav>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex h-full flex-col gap-6 bg-sidebar p-4 text-sidebar-foreground">
      <Link href="/" className="flex items-center gap-2.5 px-1" onClick={onNavigate}>
        <LogoMark className="size-9" />
        <div className="leading-tight">
          <p className="font-semibold tracking-tight">{t.appName}</p>
          <p className="text-[11px] text-sidebar-muted">{t.tagline}</p>
        </div>
      </Link>
      <Button asChild variant="accent" className="justify-start">
        <Link href="/campaigns/new" onClick={onNavigate}>
          <Plus /> {t.nav.newCampaign}
        </Link>
      </Button>
      <Suspense fallback={<div className="h-48" />}>
        <NavLinks onNavigate={onNavigate} />
      </Suspense>
      <div className="mt-auto rounded-lg border border-white/10 bg-white/5 p-3 text-[11px] text-sidebar-muted">
        {t.common.sidebarNote}
      </div>
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { t, locale, setLocale, label } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const { data: me } = useMe();
  const router = useRouter();
  const qc = useQueryClient();
  const mounted = useSyncExternalStore(noopSubscribe, () => true, () => false);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    qc.clear();
    router.replace("/login");
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur md:px-6">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onMenu} aria-label={t.common.openMenu}>
        <Menu />
      </Button>
      <div className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{me?.workspace_name}</div>
      {me?.demo_mode ? <DemoBadge /> : null}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setLocale(locale === "en" ? "ar" : "en")}
        aria-label={t.common.language}
      >
        <Languages /> {locale === "en" ? "العربية" : "English"}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t.common.theme}
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      >
        {mounted && resolvedTheme === "dark" ? <Sun /> : <Moon />}
      </Button>
      <div className="hidden text-end text-xs leading-tight sm:block">
        <p className="font-medium">{me?.user.full_name || me?.user.email}</p>
        <p className="text-muted-foreground capitalize">{me?.role ? label(me.role) : null}</p>
      </div>
      <Button variant="ghost" size="icon" onClick={logout} aria-label={t.nav.logout}>
        <LogOut />
      </Button>
    </header>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading, isError } = useMe();
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { t } = useI18n();

  useEffect(() => {
    if (isError) router.replace("/login");
  }, [isError, router]);

  if (isLoading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted-foreground">
        <Spinner /> {t.common.loading}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 start-0 z-40 hidden w-64 md:block">
        <Sidebar />
      </aside>
      {open ? (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-navy-950/60" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 start-0 w-72 shadow-xl">
            <Sidebar onNavigate={() => setOpen(false)} />
            <Button
              variant="ghost"
              size="icon"
              className="absolute end-2 top-2 text-sidebar-foreground"
              onClick={() => setOpen(false)}
              aria-label={t.common.closeMenu}
            >
              <X />
            </Button>
          </div>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col md:ms-64">
        <TopBar onMenu={() => setOpen(true)} />
        {me.demo_mode ? (
          <div className="flex items-center gap-2 border-b border-sun-500/30 bg-sun-500/10 px-4 py-2 text-xs text-foreground md:px-6">
            <FlaskConical className="size-3.5 text-sun-500" aria-hidden />
            {t.common.demoBanner}
          </div>
        ) : null}
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
