"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Fades its children up when they scroll into view. Without IntersectionObserver (tests, old browsers) or with
 * reduced motion the content is simply shown (see `.reveal` in globals.css).
 */
export function Reveal({
  children,
  className,
  delay = 0,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  as?: "div" | "li" | "section";
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(true);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    // Only hide what is still below the fold, so nothing already on screen flickers.
    if (el.getBoundingClientRect().top < window.innerHeight * 0.9) return;
    const hide = requestAnimationFrame(() => setShown(false));
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -10% 0px" },
    );
    io.observe(el);
    return () => {
      cancelAnimationFrame(hide);
      io.disconnect();
    };
  }, []);

  return (
    <Tag
      ref={ref as never}
      data-shown={shown}
      className={cn("reveal", className)}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </Tag>
  );
}

/** Concentric radar rings with a slow sweep: the brand's background motif. Decorative only. */
export function RadarBackdrop({ className, onDark = false }: { className?: string; onDark?: boolean }) {
  const ring = onDark ? "border-rasd-400/15" : "border-rasd-600/15 dark:border-rasd-400/15";
  return (
    <div aria-hidden className={cn("pointer-events-none absolute rounded-full", className)}>
      {[0, 14, 28, 42].map((inset) => (
        <div key={inset} className={cn("absolute rounded-full border", ring)} style={{ inset: `${inset}%` }} />
      ))}
      <div
        className="absolute inset-0 animate-sweep rounded-full"
        style={{
          background: onDark
            ? "conic-gradient(from 0deg, rgba(200,241,105,0.16), transparent 18%)"
            : "conic-gradient(from 0deg, rgba(16,168,119,0.12), transparent 18%)",
          maskImage: "radial-gradient(circle, black 55%, transparent 71%)",
        }}
      />
    </div>
  );
}

/** A pulsing lime dot. */
export function Ping({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex size-2.5", className)} aria-hidden>
      <span className="absolute inline-flex size-full animate-ping-slow rounded-full bg-signal-400" />
      <span className="relative inline-flex size-2.5 rounded-full bg-signal-400" />
    </span>
  );
}
