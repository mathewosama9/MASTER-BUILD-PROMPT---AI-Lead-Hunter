"use client";

import { useTheme } from "next-themes";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useI18n } from "@/i18n/provider";

/*
 * Chart colour rules (validated with the dataviz palette script):
 * - Every chart here is a single series -> one brand blue; no legend, the card title names the series.
 * - Blue #1D79FF passes 3:1 on the light surface, #4E94FF on the dark surface.
 * - Brand yellow fails 3:1 on light surfaces, so it is never used as a data mark.
 * - Histogram buckets use a sequential blue ramp (light -> dark = low -> high score).
 */
const SERIES = { light: "#1D79FF", dark: "#4E94FF" };
const RAMP = {
  light: ["#99C2FF", "#6FA8FF", "#4E94FF", "#1D79FF", "#0049B2"],
  dark: ["#25275F", "#2E4C99", "#1D79FF", "#4E94FF", "#99C2FF"],
};

function usePalette() {
  const { resolvedTheme } = useTheme();
  const mode: "light" | "dark" = resolvedTheme === "light" ? "light" : "dark";
  return {
    series: SERIES[mode],
    ramp: RAMP[mode],
    grid: mode === "dark" ? "#25275F" : "#E3E4F3",
    axis: mode === "dark" ? "#9A9CC9" : "#4B4D83",
    tooltipBg: mode === "dark" ? "#0E0F31" : "#FFFFFF",
    tooltipBorder: mode === "dark" ? "#25275F" : "#D9DBEF",
    text: mode === "dark" ? "#F2F3FF" : "#0E0F31",
  };
}

function tooltipStyle(p: ReturnType<typeof usePalette>) {
  return {
    contentStyle: {
      background: p.tooltipBg,
      border: `1px solid ${p.tooltipBorder}`,
      borderRadius: 8,
      fontSize: 12,
      color: p.text,
    },
    labelStyle: { color: p.axis },
    itemStyle: { color: p.text },
  };
}

function SrTable({ rows, label }: { rows: { label: string; value: number }[]; label: string }) {
  return (
    <table className="sr-only">
      <caption>{label}</caption>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <th scope="row">{r.label}</th>
            <td>{r.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TrendChart({ data, label }: { data: { date: string; count: number }[]; label: string }) {
  const p = usePalette();
  const { locale } = useI18n();
  const fmt = (d: string) =>
    new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en-GB", { day: "numeric", month: "short" }).format(new Date(d));
  return (
    <div className="h-56 w-full" dir="ltr">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={p.series} stopOpacity={0.35} />
              <stop offset="100%" stopColor={p.series} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={p.grid} vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmt} tick={{ fill: p.axis, fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis allowDecimals={false} tick={{ fill: p.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip
            {...tooltipStyle(p)}
            labelFormatter={(v) => fmt(String(v))}
            cursor={{ stroke: p.axis, strokeDasharray: "3 3" }}
          />
          <Area isAnimationActive={false} type="monotone" dataKey="count" name={label} stroke={p.series} strokeWidth={2} fill="url(#trendFill)" activeDot={{ r: 4 }} />
        </AreaChart>
      </ResponsiveContainer>
      <SrTable label={label} rows={data.map((d) => ({ label: d.date, value: d.count }))} />
    </div>
  );
}

export function HBarChart({
  data,
  label,
  format = (k) => k,
}: {
  data: { key: string; count: number }[];
  label: string;
  format?: (k: string) => string;
}) {
  const p = usePalette();
  const rows = data.map((d) => ({ name: format(d.key), count: d.count }));
  const height = Math.max(120, rows.length * 30 + 20);
  return (
    <div style={{ height }} className="w-full" dir="ltr">
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 24, left: 0, bottom: 0 }} barCategoryGap={6}>
          <CartesianGrid stroke={p.grid} horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: p.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="name" width={110} tick={{ fill: p.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip {...tooltipStyle(p)} cursor={{ fill: p.grid, opacity: 0.4 }} />
          <Bar isAnimationActive={false} dataKey="count" name={label} fill={p.series} radius={[0, 4, 4, 0]} maxBarSize={18} />
        </BarChart>
      </ResponsiveContainer>
      <SrTable label={label} rows={rows.map((r) => ({ label: r.name, value: r.count }))} />
    </div>
  );
}

export function ScoreHistogram({ data, label }: { data: { bucket: string; count: number }[]; label: string }) {
  const p = usePalette();
  return (
    <div className="h-48 w-full" dir="ltr">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }} barCategoryGap={2}>
          <CartesianGrid stroke={p.grid} vertical={false} />
          <XAxis dataKey="bucket" tick={{ fill: p.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis allowDecimals={false} tick={{ fill: p.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip {...tooltipStyle(p)} cursor={{ fill: p.grid, opacity: 0.4 }} />
          <Bar isAnimationActive={false} dataKey="count" name={label} radius={[4, 4, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={d.bucket} fill={p.ramp[i] ?? p.series} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <SrTable label={label} rows={data.map((d) => ({ label: d.bucket, value: d.count }))} />
    </div>
  );
}
