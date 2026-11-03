/**
 * A hash of this browser's traits (screen, timezone, graphics, canvas rendering...), sent with sign-up and sign-in
 * so the platform admin can spot a second account made on the same machine even after cookies are cleared. It is
 * weak evidence on its own (identical phones share it) and only ever compared, never shown to the customer.
 */
async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function canvasTrait(): string {
  const canvas = document.createElement("canvas");
  canvas.width = 220;
  canvas.height = 40;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  ctx.textBaseline = "top";
  ctx.font = "16px Arial";
  ctx.fillStyle = "#c8f169";
  ctx.fillRect(0, 0, 220, 40);
  ctx.fillStyle = "#071a17";
  ctx.fillText("Rasd رصد 👀 0123", 4, 10);
  return canvas.toDataURL();
}

function webglTrait(): string {
  const gl = document.createElement("canvas").getContext("webgl");
  if (!gl) return "";
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  return info ? `${gl.getParameter(info.UNMASKED_VENDOR_WEBGL)}|${gl.getParameter(info.UNMASKED_RENDERER_WEBGL)}` : "";
}

export async function deviceFingerprint(): Promise<string | undefined> {
  try {
    const nav = navigator as Navigator & { deviceMemory?: number };
    const traits = [
      nav.userAgent,
      nav.language,
      nav.hardwareConcurrency,
      nav.deviceMemory ?? "",
      nav.maxTouchPoints,
      `${screen.width}x${screen.height}x${screen.colorDepth}@${window.devicePixelRatio}`,
      Intl.DateTimeFormat().resolvedOptions().timeZone,
      webglTrait(),
      await sha256(canvasTrait()),
    ];
    return await sha256(traits.join("~"));
  } catch {
    return undefined; // no secure context or a privacy browser: sign-up works the same without it
  }
}
