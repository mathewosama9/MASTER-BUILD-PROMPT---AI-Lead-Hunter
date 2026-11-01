"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquareHeart, Star } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, Checkbox, Dialog, Field, Input, Textarea } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface MyReview {
  rating: number;
  status: string;
  consent_publish: boolean;
  created_at: string;
}

export function useMyReview() {
  return useQuery({ queryKey: ["my-review"], queryFn: () => api<MyReview | null>("/reviews/mine"), staleTime: 5 * 60_000 });
}

function StarInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const { t } = useI18n();
  return (
    <div className="flex gap-1" role="radiogroup" aria-label={t.overview.review.rating}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={String(n)}
          onClick={() => onChange(n)}
          className="rounded-md p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Star className={cn("size-7 transition-colors", n <= value ? "fill-sun-500 text-sun-500" : "text-muted-foreground/40")} />
        </button>
      ))}
    </div>
  );
}

/** The user's own review: stars, text, optional role/city and explicit consent to publish it on the site. */
export function ReviewDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useI18n();
  const r = t.overview.review;
  const qc = useQueryClient();
  const [rating, setRating] = useState(5);
  const [body, setBody] = useState("");
  const [role, setRole] = useState("");
  const [city, setCity] = useState("");
  const [consent, setConsent] = useState(true);
  const send = useMutation({
    mutationFn: () =>
      api("/reviews", { method: "POST", body: { rating, body, author_role: role || null, city: city || null, consent_publish: consent } }),
    onSuccess: () => {
      toast.success(r.thanks);
      void qc.invalidateQueries({ queryKey: ["my-review"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={r.title}
      description={r.body}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {r.later}
          </Button>
          <Button variant="ink" disabled={body.trim().length < 10 || send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? <Spinner /> : null} {r.submit}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={r.rating} htmlFor="review_rating">
          <StarInput value={rating} onChange={setRating} />
        </Field>
        <Field label={r.text} htmlFor="review_body">
          <Textarea id="review_body" rows={4} maxLength={1000} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={r.role} htmlFor="review_role">
            <Input id="review_role" placeholder={r.rolePlaceholder} maxLength={120} value={role} onChange={(e) => setRole(e.target.value)} />
          </Field>
          <Field label={r.city} htmlFor="review_city">
            <Input id="review_city" maxLength={120} value={city} onChange={(e) => setCity(e.target.value)} />
          </Field>
        </div>
        <label className="flex items-start gap-2.5 text-sm">
          <span className="mt-0.5">
            <Checkbox checked={consent} onCheckedChange={setConsent} aria-label={r.consent} />
          </span>
          {r.consent}
        </label>
      </div>
    </Dialog>
  );
}

const DISMISS_KEY = "rasd-review-dismissed";

/** Asks for a review once the user has run a real search, until they leave one or dismiss it. */
export function ReviewPrompt() {
  const { t } = useI18n();
  const r = t.overview.review;
  const mine = useMyReview();
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return typeof window !== "undefined" && window.localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });
  if (dismissed || mine.isLoading || mine.data) return null;
  const dismiss = () => {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* storage unavailable */
    }
    setDismissed(true);
  };
  return (
    <Card className="border-rasd-600/25 bg-rasd-50/60 dark:bg-rasd-500/5">
      <CardContent className="flex flex-wrap items-center gap-4 p-5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-ink-900 text-signal-400">
          <MessageSquareHeart className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{r.title}</p>
          <p className="text-sm text-muted-foreground">{r.body}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={dismiss}>
            {r.later}
          </Button>
          <Button variant="ink" size="sm" onClick={() => setOpen(true)}>
            {r.open}
          </Button>
        </div>
      </CardContent>
      <ReviewDialog open={open} onOpenChange={setOpen} />
    </Card>
  );
}
