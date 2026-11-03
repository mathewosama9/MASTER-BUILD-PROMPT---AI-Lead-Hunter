"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  ChevronDown,
  Coins,
  FlaskConical,
  Globe,
  Hourglass,
  Languages,
  LayoutDashboard,
  LogOut,
  MessageSquareHeart,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Moon,
  Plus,
  Radar,
  Settings,
  ShieldCheck,
  Sun,
  Users,
  Wallet,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Dialog as RDialog, DropdownMenu as RMenu } from "radix-ui";
import { Suspense, useEffect, useState, useSyncExternalStore } from "react";

import { DemoBadge } from "@/components/badges";
import { Lockup, LogoMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/states";
import { VerifyEmailBanner } from "@/features/auth/account-forms";
import { ReviewDialog } from "@/features/dashboard/review";
import { ImpersonationStrip } from "@/features/admin/ops";
import { NotificationBell } from "@/features/notifications/bell";
import { TelegramStrip } from "@/features/settings/telegram-strip";
import { useBillingSummary, useMe } from "@/hooks/queries";
import { hasSavedLocale, useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, formatNumber } from "@/lib/utils";

const noopSubscribe = () => () => {};

// The desktop sidebar can fold down to icons; the choice is remembered per browser.
const SIDEBAR_KEY = "rasd-sidebar-collapsed";
const SIDEBAR_EVENT = "rasd-sidebar";
function subscribeSidebar(cb: () => void) {
  window.addEventListener(SIDEBAR_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(SIDEBAR_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}
function readSidebar() {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}
function setSidebarCollapsed(v: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_KEY, v ? "1" : "0");
  } catch {
    // private mode: the toggle still works until the next page load
  }
  window.dispatchEvent(new Event(SIDEBAR_EVENT));
}
function useSidebarCollapsed() {
  return useSyncExternalStore(subscribeSidebar, readSidebar, () => false);
}

// Daily work first (home, the leads to call, the searches); account pages below a divider.
const NAV_PRIMARY = [
  { href: "/app", key: "overview", icon: LayoutDashboard },
  { href: "/app/leads", key: "leads", icon: Users },
  { href: "/app/campaigns", key: "campaigns", icon: Radar },
] as const;

const NAV_SECONDARY = [
  { href: "/app/billing", key: "billing", icon: Wallet },
  { href: "/app/settings", key: "settings", icon: Settings },
  { href: "/app/suppression", key: "suppression", icon: Ban },
] as const;

const ADMIN_NAV = { href: "/app/admin", key: "admin", icon: ShieldCheck } as const;

type NavItem = { href: string; key: keyof ReturnType<typeof useI18n>["t"]["nav"]; icon: React.ComponentType<{ className?: string }> };

function isActive(pathname: string, href: string) {
  return href === "/app" ? pathname === "/app" : pathname.startsWith(href) && !(href === "/app/campaigns" && pathname === "/app/campaigns/new");
}

function NavLinks({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const { t } = useI18n();
  const { data: me } = useMe();
  const secondary: readonly NavItem[] = me?.user.is_superuser ? [...NAV_SECONDARY, ADMIN_NAV] : NAV_SECONDARY;
  return (
    <nav className="flex flex-col gap-0.5" aria-label={t.common.mainNav}>
      <NavGroup items={NAV_PRIMARY} onNavigate={onNavigate} collapsed={collapsed} />
      <div className={cn("my-3 h-px bg-white/10", collapsed ? "mx-1" : "mx-3")} aria-hidden />
      <NavGroup items={secondary} onNavigate={onNavigate} collapsed={collapsed} />
    </nav>
  );
}

function NavGroup({ items, onNavigate, collapsed = false }: { items: readonly NavItem[]; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  const { t } = useI18n();
  return (
    <>
      {items.map(({ href, key, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            aria-label={collapsed ? t.nav[key] : undefined}
            title={collapsed ? t.nav[key] : undefined}
            className={cn(
              "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-muted transition-colors hover:bg-white/5 hover:text-sidebar-foreground",
              collapsed && "justify-center px-0",
              active && "bg-white/[0.08] font-medium text-sidebar-foreground",
            )}
          >
            <Icon className={cn("size-4 shrink-0", active ? "text-signal-400" : "text-sidebar-muted group-hover:text-rasd-300")} />
            {collapsed ? null : t.nav[key]}
            {active ? (
              <span aria-hidden className={cn("size-1.5 rounded-full bg-signal-400", collapsed ? "absolute end-1 top-1" : "ms-auto")} />
            ) : null}
          </Link>
        );
      })}
    </>
  );
}

/** Thumb-reach navigation on phones: the daily pages, a raised "new search" button, and "more" for the rest. */
function BottomNav({ onMore }: { onMore: () => void }) {
  const pathname = usePathname();
  const { t } = useI18n();
  const tab = "flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";
  const link = (href: string, key: NavItem["key"], Icon: NavItem["icon"]) => {
    const active = isActive(pathname, href);
    return (
      <Link href={href} aria-current={active ? "page" : undefined} className={cn(tab, active ? "font-medium text-foreground" : "text-muted-foreground")}>
        <Icon className={cn("size-5", active && "text-rasd-600 dark:text-signal-400")} />
        {t.nav[key]}
      </Link>
    );
  };
  return (
    <nav
      aria-label={t.common.mainNav}
      className="fixed inset-x-0 bottom-0 z-40 flex items-stretch border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      {link("/app", "overview", LayoutDashboard)}
      {link("/app/leads", "leads", Users)}
      <Link href="/app/campaigns/new" className={cn(tab, "text-foreground")} aria-label={t.nav.newCampaign}>
        <span className="-mt-6 flex size-12 items-center justify-center rounded-full bg-signal-400 text-ink-900 shadow-lg shadow-ink-900/20 ring-4 ring-background">
          <Plus className="size-6" />
        </span>
        <span className="max-w-20 truncate">{t.nav.newCampaign}</span>
      </Link>
      {link("/app/campaigns", "campaigns", Radar)}
      <button type="button" onClick={onMore} className={cn(tab, "text-muted-foreground")}>
        <MoreHorizontal className="size-5" />
        {t.nav.more}
      </button>
    </nav>
  );
}

/** Balance at a glance in the sidebar, with the trial countdown and a top-up shortcut. */
function CreditCard({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const { t, locale } = useI18n();
  const { data: s } = useBillingSummary();
  if (collapsed) {
    if (!s || s.billing_exempt) return null;
    const warn = s.low_balance || s.trial_expired;
    return (
      <Link
        href="/app/billing"
        onClick={onNavigate}
        title={`${t.common.creditsLeft}: ${formatNumber(s.balance, locale)}`}
        className={cn(
          "flex flex-col items-center gap-0.5 rounded-lg border px-1 py-2 text-[11px] tabular-nums",
          warn ? "border-sun-500/40 bg-sun-500/10 text-sun-400" : "border-white/10 bg-white/5 text-sidebar-foreground",
        )}
      >
        {warn ? <AlertTriangle className="size-3.5" aria-hidden /> : <Coins className="size-3.5" aria-hidden />}
        {formatNumber(s.balance, locale)}
      </Link>
    );
  }
  if (!s) return <div className="h-28" />;
  if (s.billing_exempt) {
    return <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-sidebar-muted">{t.common.unlimited}</div>;
  }
  const warn = s.low_balance || s.trial_expired;
  return (
    <div className={cn("rounded-xl border p-4", warn ? "border-sun-500/40 bg-sun-500/10" : "border-white/10 bg-white/5")}>
      <p className="flex items-center gap-1.5 text-xs text-sidebar-muted">
        {warn ? <AlertTriangle className="size-3.5 text-sun-400" aria-hidden /> : <Coins className="size-3.5" aria-hidden />}
        {s.trial_expired ? t.billing.badgeTrialEnded : t.common.creditsLeft}
      </p>
      <p className="mt-1 font-display text-2xl font-bold tabular-nums text-sidebar-foreground">{formatNumber(s.balance, locale)}</p>
      {s.on_trial && s.trial_days_left !== null && !s.trial_expired ? (
        <p className="text-[11px] text-sidebar-muted">{t.common.trialLeft.replace("{n}", String(s.trial_days_left))}</p>
      ) : null}
      <Button asChild size="sm" variant="accent" className="mt-3 w-full">
        <Link href="/app/billing" onClick={onNavigate}>
          {t.common.topUp}
        </Link>
      </Button>
    </div>
  );
}

function Sidebar({ onNavigate, collapsed = false, onToggle }: { onNavigate?: () => void; collapsed?: boolean; onToggle?: () => void }) {
  const { t, locale } = useI18n();
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;
  return (
    <div className={cn("flex h-full flex-col gap-6 overflow-y-auto overflow-x-hidden bg-sidebar text-sidebar-foreground", collapsed ? "px-2 py-4" : "p-4")}>
      <div className={cn("flex items-center gap-2", collapsed ? "flex-col" : "justify-between")}>
        <Link href="/app" className={cn("pt-1", !collapsed && "px-1")} onClick={onNavigate} aria-label={t.appName}>
          {collapsed ? <LogoMark className="size-9" /> : <Lockup locale={locale} markClassName="size-9" />}
        </Link>
        {onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? t.common.expandSidebar : t.common.collapseSidebar}
            aria-expanded={!collapsed}
            title={collapsed ? t.common.expandSidebar : t.common.collapseSidebar}
            className="rounded-md p-1.5 text-sidebar-muted transition-colors hover:bg-white/5 hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-400"
          >
            <ToggleIcon className="size-4 rtl:rotate-180" aria-hidden />
          </button>
        ) : null}
      </div>
      <Button asChild variant="accent" className={collapsed ? "justify-center px-0" : "justify-start"}>
        <Link href="/app/campaigns/new" onClick={onNavigate} aria-label={collapsed ? t.nav.newCampaign : undefined} title={collapsed ? t.nav.newCampaign : undefined}>
          <Plus /> {collapsed ? null : t.nav.newCampaign}
        </Link>
      </Button>
      <Suspense fallback={<div className="h-48" />}>
        <NavLinks onNavigate={onNavigate} collapsed={collapsed} />
      </Suspense>
      <div className="mt-auto">
        <CreditCard onNavigate={onNavigate} collapsed={collapsed} />
      </div>
    </div>
  );
}

/** Compact balance chip for the top bar on small screens, where the sidebar is hidden. */
function CreditBadge() {
  const { t, locale } = useI18n();
  const { data: s } = useBillingSummary();
  if (!s || s.billing_exempt) return null;
  const warn = s.low_balance || s.trial_expired;
  const text = s.awaiting_verification
    ? t.account.badgeConfirm
    : s.awaiting_approval
      ? t.account.badgePending
      : s.trial_expired
      ? t.billing.badgeTrialEnded
      : t.billing.badge.replace("{n}", formatNumber(s.balance, locale));
  return (
    <Link
      href="/app/billing"
      title={s.low_balance && !s.trial_expired && !s.awaiting_verification ? t.billing.lowBalance : undefined}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium tabular-nums transition-colors md:hidden",
        s.trial_expired
          ? "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300"
          : warn
            ? "border-sun-500/50 bg-sun-500/10 text-[#7a5700] dark:text-sun-400"
            : "border-border hover:bg-muted",
      )}
    >
      {warn ? <AlertTriangle className="size-3.5" aria-hidden /> : <Coins className="size-3.5" aria-hidden />}
      {text}
    </Link>
  );
}

function initials(name: string) {
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

function UserMenu() {
  const { t, locale, setLocale, label } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const { data: me } = useMe();
  const router = useRouter();
  const qc = useQueryClient();
  const mounted = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const name = me?.user.full_name || me?.user.email || "";
  const dark = mounted && resolvedTheme === "dark";

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    qc.clear();
    router.replace("/login");
  }

  const item =
    "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-muted";
  return (
    <>
      <RMenu.Root dir={locale === "ar" ? "rtl" : "ltr"}>
        <RMenu.Trigger className="flex items-center gap-2 rounded-full p-1 pe-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="flex size-8 items-center justify-center rounded-full bg-ink-900 font-display text-xs font-semibold text-signal-400">
            {initials(name)}
          </span>
          <span className="hidden text-start text-xs leading-tight sm:block">
            <span className="block max-w-36 truncate font-medium">{name}</span>
            <span className="block text-muted-foreground">{me?.role ? label(me.role) : null}</span>
          </span>
          <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden />
        </RMenu.Trigger>
        <RMenu.Portal>
          <RMenu.Content align="end" sideOffset={8} className="z-50 w-60 rounded-xl border bg-card p-1.5 text-card-foreground shadow-xl">
            <div className="px-2.5 py-2">
              <p className="truncate text-sm font-medium">{name}</p>
              <p className="truncate text-xs text-muted-foreground">{me?.workspace_name}</p>
            </div>
            <RMenu.Separator className="my-1 h-px bg-border" />
            <RMenu.Item className={item} onSelect={() => setLocale(locale === "en" ? "ar" : "en")}>
              <Languages className="size-4" /> {locale === "en" ? "العربية" : "English"}
            </RMenu.Item>
            <RMenu.Item className={item} onSelect={() => setTheme(dark ? "light" : "dark")}>
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />} {dark ? t.common.lightMode : t.common.darkMode}
            </RMenu.Item>
            <RMenu.Item className={item} onSelect={() => setReviewOpen(true)}>
              <MessageSquareHeart className="size-4" /> {t.common.rateUs}
            </RMenu.Item>
            <RMenu.Item asChild className={item}>
              <Link href="/">
                <Globe className="size-4" /> {t.common.website}
              </Link>
            </RMenu.Item>
            <RMenu.Separator className="my-1 h-px bg-border" />
            <RMenu.Item className={cn(item, "text-destructive")} onSelect={() => void logout()}>
              <LogOut className="size-4" /> {t.nav.logout}
            </RMenu.Item>
          </RMenu.Content>
        </RMenu.Portal>
      </RMenu.Root>
      <ReviewDialog open={reviewOpen} onOpenChange={setReviewOpen} />
    </>
  );
}

function TopBar() {
  const { t } = useI18n();
  const { data: me } = useMe();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur md:h-16 md:px-6">
      {/* Phones navigate from the bottom bar; the top keeps only the brand, balance and account. */}
      <Link href="/app" className="md:hidden" aria-label={t.appName}>
        <LogoMark className="size-8" />
      </Link>
      <div className="min-w-0 flex-1 truncate text-sm font-medium text-muted-foreground">{me?.workspace_name}</div>
      <CreditBadge />
      {me?.demo_mode ? <DemoBadge /> : null}
      <NotificationBell />
      <UserMenu />
    </header>
  );
}

function EmailStrip({ email }: { email: string }) {
  const { data: s } = useBillingSummary();
  return <VerifyEmailBanner email={email} trialPending={!!s?.awaiting_verification} />;
}

/** A new self-signup waits for the platform admin's approval before its free trial starts. */
function ReviewStrip() {
  const { t } = useI18n();
  const { data: s } = useBillingSummary();
  if (!s?.awaiting_approval) return null;
  return (
    <div role="status" className="flex items-center gap-2 border-b border-sun-500/30 bg-sun-500/10 px-4 py-2 text-xs text-foreground md:px-6">
      <Hourglass className="size-4 shrink-0 text-sun-500" aria-hidden />
      {t.account.pendingBanner}
    </div>
  );
}

/** Mobile navigation drawer with focus trap and Escape-to-close (Radix Dialog). */
function MobileNav({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useI18n();
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-50 bg-ink-950/60 backdrop-blur-sm md:hidden" />
        <RDialog.Content className="fixed inset-y-0 start-0 z-50 w-72 shadow-2xl md:hidden">
          <RDialog.Title className="sr-only">{t.common.mainNav}</RDialog.Title>
          <RDialog.Description className="sr-only">{t.common.mainNav}</RDialog.Description>
          <Sidebar onNavigate={() => onOpenChange(false)} />
          <RDialog.Close asChild>
            <Button variant="ghost" size="icon" className="absolute end-2 top-3 text-sidebar-foreground hover:bg-white/10" aria-label={t.common.closeMenu}>
              <X />
            </Button>
          </RDialog.Close>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading, isError } = useMe();
  const [open, setOpen] = useState(false);
  const collapsed = useSidebarCollapsed();
  const router = useRouter();
  const qc = useQueryClient();
  const { t, locale, setLocale } = useI18n();

  useEffect(() => {
    if (isError) router.replace("/login");
  }, [isError, router]);

  // Emails and Telegram follow the dashboard language. A browser that never picked one takes the account's language;
  // one the user switched tells the server, so the next email matches what they read here.
  // Not while an admin views the account: that session is read-only, and the language is the customer's.
  const savedLocale = me?.impersonated_by ? undefined : me?.user.locale;
  useEffect(() => {
    if (!savedLocale || savedLocale === locale) return;
    if (!hasSavedLocale()) {
      if (savedLocale === "ar" || savedLocale === "en") setLocale(savedLocale);
      return;
    }
    void api("/auth/locale", { method: "PUT", body: { locale } })
      .then(() => qc.invalidateQueries({ queryKey: ["me"] }))
      .catch(() => undefined);
  }, [savedLocale, locale, qc, setLocale]);

  if (isLoading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted-foreground">
        <Spinner /> {t.common.loading}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside className={cn("fixed inset-y-0 start-0 z-40 hidden transition-[width] duration-200 md:block", collapsed ? "w-16" : "w-64")}>
        <Sidebar collapsed={collapsed} onToggle={() => setSidebarCollapsed(!collapsed)} />
      </aside>
      <MobileNav open={open} onOpenChange={setOpen} />
      <BottomNav onMore={() => setOpen(true)} />
      <div className={cn("flex min-w-0 flex-1 flex-col transition-[margin] duration-200", collapsed ? "md:ms-16" : "md:ms-64")}>
        <TopBar />
        {me.demo_mode ? (
          <div className="flex items-center gap-2 border-b border-sun-500/30 bg-sun-500/10 px-4 py-2 text-xs text-foreground md:px-6">
            <FlaskConical className="size-3.5 text-sun-500" aria-hidden />
            {t.common.demoBanner}
          </div>
        ) : null}
        {me.impersonated_by ? <ImpersonationStrip email={me.user.email} /> : null}
        {/* Both strips act (POST), which an admin viewing the account cannot do. */}
        {me.user.email_verified_at === null && !me.impersonated_by ? <EmailStrip email={me.user.email} /> : null}
        {/* Viewers cannot create link codes; everyone else sees this until Telegram is linked. */}
        {me.telegram_status && me.telegram_status !== "linked" && me.role !== "viewer" && !me.impersonated_by ? (
          <TelegramStrip status={me.telegram_status} />
        ) : null}
        {me.user.approval_status === "pending" ? <ReviewStrip /> : null}
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 pb-28 md:p-6">{children}</main>
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
