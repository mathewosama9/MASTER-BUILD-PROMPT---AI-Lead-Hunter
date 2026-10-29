"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Campaign, DashboardStats, JobEvent, LeadDetail, LeadRow, Me, Meta, Page, Provider } from "@/types/api";

export const ACTIVE = ["queued", "discovering", "enriching", "analyzing"];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me"), staleTime: 60_000, retry: false });
}

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
}

export function useProviders() {
  return useQuery({ queryKey: ["providers"], queryFn: () => api<Provider[]>("/providers") });
}

export function useDashboard(isDemo?: boolean) {
  return useQuery({
    queryKey: ["dashboard", isDemo],
    queryFn: () => api<DashboardStats>("/dashboard/stats", { query: { is_demo: isDemo } }),
    refetchInterval: 15_000,
  });
}

export function useCampaigns(params: Record<string, string | number | boolean | undefined>) {
  return useQuery({
    queryKey: ["campaigns", params],
    queryFn: () => api<Page<Campaign>>("/campaigns", { query: params }),
    refetchInterval: (q) => (q.state.data?.items.some((c) => ACTIVE.includes(c.status)) ? 4000 : false),
  });
}

export function useLeads(params: Record<string, string | number | boolean | undefined>) {
  return useQuery({
    queryKey: ["leads", params],
    queryFn: () => api<Page<LeadRow>>("/leads", { query: params }),
    placeholderData: (prev) => prev,
  });
}

export function useLead(id: string) {
  return useQuery({ queryKey: ["lead", id], queryFn: () => api<LeadDetail>(`/leads/${id}`) });
}

export interface LiveProgress {
  activity?: string | null;
  /** Translatable form of `activity`: `{ t: template key, p: params }`. */
  activity_t?: { t: string; p: Record<string, unknown> } | null;
  provider?: string | null;
  cost?: { discovery: number; ai: number };
}

/**
 * Live campaign state: Server-Sent Events first, polling fallback when SSE is unavailable or drops.
 */
export function useCampaignLive(id: string) {
  const qc = useQueryClient();
  const [transport, setTransport] = useState<"sse" | "polling">(() =>
    typeof EventSource === "undefined" ? "polling" : "sse",
  );
  const [live, setLive] = useState<LiveProgress>({});
  const [liveEvents, setLiveEvents] = useState<JobEvent[]>([]);
  const lastEventAt = useRef<string | null>(null);

  const campaign = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => api<Campaign>(`/campaigns/${id}`),
    refetchInterval: (q) => (transport === "polling" && q.state.data && ACTIVE.includes(q.state.data.status) ? 3000 : false),
  });
  const active = campaign.data ? ACTIVE.includes(campaign.data.status) || campaign.data.status === "paused" : false;

  // When the run reaches a terminal state (via SSE progress, status or polling), refresh everything derived
  // from it once: full campaign record (sources, errors), results table and dashboard.
  const status = campaign.data?.status;
  const prevStatus = useRef(status);
  useEffect(() => {
    const was = prevStatus.current;
    prevStatus.current = status;
    if (was && status && was !== status && !ACTIVE.includes(status)) {
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["campaign-events", id] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    }
  }, [status, id, qc]);

  // Initial history + polling for new events in fallback mode.
  const history = useQuery({
    queryKey: ["campaign-events", id],
    queryFn: () => api<JobEvent[]>(`/campaigns/${id}/events/history`, { query: { limit: 200 } }),
  });
  const events = useMemo(() => {
    const base = history.data ?? [];
    const seen = new Set(base.map((e) => e.id));
    return [...base, ...liveEvents.filter((e) => !seen.has(e.id))];
  }, [history.data, liveEvents]);
  useEffect(() => {
    lastEventAt.current = events.at(-1)?.created_at ?? null;
  }, [events]);

  useEffect(() => {
    if (transport !== "polling" || !active) return;
    const timer = setInterval(async () => {
      try {
        const fresh = await api<JobEvent[]>(`/campaigns/${id}/events/history`, {
          query: { since: lastEventAt.current ?? undefined, limit: 200 },
        });
        if (fresh.length) {
          lastEventAt.current = fresh.at(-1)!.created_at;
          setLiveEvents((prev) => [...prev, ...fresh.filter((e) => !prev.some((p) => p.id === e.id))]);
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [transport, active, id]);

  useEffect(() => {
    if (!active || transport !== "sse") return;
    const es = new EventSource(`/api/v1/campaigns/${id}/events`, { withCredentials: true });
    let opened = false;
    let lastMessage = Date.now();
    const touch = () => {
      lastMessage = Date.now();
    };
    ["snapshot", "progress", "event", "status", "ping"].forEach((name) => es.addEventListener(name, touch));
    // Watchdog: the server sends a heartbeat at least every 15s. If nothing arrives (e.g. a buffering proxy),
    // fall back to polling so the monitor never freezes.
    const watchdog = setInterval(() => {
      if (Date.now() - lastMessage > 20_000) {
        es.close();
        setTransport("polling");
      }
    }, 5_000);
    es.addEventListener("snapshot", (e) => {
      opened = true;
      qc.setQueryData(["campaign", id], JSON.parse((e as MessageEvent).data));
    });
    es.addEventListener("progress", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setLive({ activity: data.activity, activity_t: data.activity_t, provider: data.provider, cost: data.cost });
      qc.setQueryData<Campaign>(["campaign", id], (prev) =>
        prev ? { ...prev, status: data.status, stage: data.stage, stats: data.stats, cost_discovery: data.cost?.discovery ?? prev.cost_discovery, cost_ai: data.cost?.ai ?? prev.cost_ai } : prev,
      );
    });
    es.addEventListener("event", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as JobEvent;
      lastEventAt.current = ev.created_at;
      setLiveEvents((prev) => (prev.some((p) => p.id === ev.id) ? prev : [...prev, ev]));
    });
    es.addEventListener("status", () => {
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["leads"] });
    });
    es.addEventListener("error", () => {
      if (!opened || es.readyState === EventSource.CLOSED) {
        es.close();
        setTransport("polling");
      }
    });
    return () => {
      clearInterval(watchdog);
      es.close();
    };
  }, [active, id, qc, transport]);

  return { campaign, events, live, transport };
}
