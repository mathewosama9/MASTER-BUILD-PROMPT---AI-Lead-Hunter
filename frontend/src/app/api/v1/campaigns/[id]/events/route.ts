// Streaming proxy for Server-Sent Events. Generic rewrites may buffer responses; this handler pipes the
// upstream event stream through unbuffered and forwards the session cookie.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export async function GET(request: Request, ctx: RouteContext<"/api/v1/campaigns/[id]/events">) {
  const { id } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new Response("Not found", { status: 404 });
  const upstream = await fetch(`${API_INTERNAL_URL}/api/v1/campaigns/${id}/events`, {
    headers: { cookie: request.headers.get("cookie") ?? "", accept: "text/event-stream" },
    signal: request.signal,
    cache: "no-store",
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "text/event-stream",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
      connection: "keep-alive",
    },
  });
}
