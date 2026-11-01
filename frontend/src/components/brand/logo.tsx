// Rasd (رصد) brand marks: a radar whose sweep arcs read as the letter "ر", with a lime "ping" on the found client.

import { cn } from "@/lib/utils";

/** Arcs and ping only, in `currentColor` + lime; reused by the tile mark and the OG image. */
export function RadarGlyph({ className, arcs = "currentColor" }: { className?: string; arcs?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden fill="none">
      <path d="M18 16A30 30 0 0 1 48 46" stroke={arcs} strokeOpacity="0.45" strokeWidth="5.5" strokeLinecap="round" />
      <path d="M18 26A20 20 0 0 1 38 46" stroke={arcs} strokeOpacity="0.8" strokeWidth="5.5" strokeLinecap="round" />
      <path d="M18 36A10 10 0 0 1 28 46" stroke="#C8F169" strokeWidth="5.5" strokeLinecap="round" />
      <circle cx="18" cy="46" r="4.5" fill="#C8F169" />
      <circle cx="39.2" cy="24.8" r="8" fill="#C8F169" fillOpacity="0.25" />
      <circle cx="39.2" cy="24.8" r="4.2" fill="#C8F169" />
    </svg>
  );
}

/** The app icon: radar glyph on an ink tile. */
export function LogoMark({ className = "size-8" }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center rounded-[28%] bg-ink-900", className)}>
      <RadarGlyph className="size-[82%] text-rasd-400" />
    </span>
  );
}

/** Mark + name. The name follows the reading language: "رصد" in Arabic, "Rasd" in English. */
export function Lockup({
  locale,
  className,
  markClassName = "size-8",
  textClassName,
}: {
  locale: "ar" | "en";
  className?: string;
  markClassName?: string;
  textClassName?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark className={markClassName} />
      <span className={cn("font-display text-xl font-bold leading-none tracking-tight", textClassName)}>
        {locale === "ar" ? "رصد" : "Rasd"}
      </span>
    </span>
  );
}
