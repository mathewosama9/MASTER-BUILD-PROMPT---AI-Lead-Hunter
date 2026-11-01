import { ImageResponse } from "next/og";

export const alt = "Rasd · رصد: your next clients, on the radar";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// The OG renderer has no Arabic font by default, so the card is drawn in English with the brand glyph.
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: "#071a17", position: "relative" }}>
        <svg width="760" height="760" viewBox="0 0 64 64" fill="none" style={{ position: "absolute", right: -160, bottom: -250 }}>
          <path d="M18 6A40 40 0 0 1 58 46" stroke="#3cc594" strokeOpacity="0.12" strokeWidth="2" />
          <path d="M18 16A30 30 0 0 1 48 46" stroke="#3cc594" strokeOpacity="0.2" strokeWidth="2" />
          <path d="M18 26A20 20 0 0 1 38 46" stroke="#3cc594" strokeOpacity="0.3" strokeWidth="2" />
          <path d="M18 36A10 10 0 0 1 28 46" stroke="#c8f169" strokeOpacity="0.5" strokeWidth="2" />
        </svg>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", padding: "0 96px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
            <div style={{ width: 120, height: 120, borderRadius: 34, background: "#0d2722", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="100" height="100" viewBox="0 0 64 64" fill="none">
                <path d="M18 16A30 30 0 0 1 48 46" stroke="#3cc594" strokeOpacity="0.45" strokeWidth="5.5" strokeLinecap="round" />
                <path d="M18 26A20 20 0 0 1 38 46" stroke="#3cc594" strokeOpacity="0.8" strokeWidth="5.5" strokeLinecap="round" />
                <path d="M18 36A10 10 0 0 1 28 46" stroke="#c8f169" strokeWidth="5.5" strokeLinecap="round" />
                <circle cx="18" cy="46" r="4.5" fill="#c8f169" />
                <circle cx="39.2" cy="24.8" r="4.2" fill="#c8f169" />
              </svg>
            </div>
            <div style={{ fontSize: 112, fontWeight: 700, color: "#eef5f1", letterSpacing: -3 }}>Rasd</div>
          </div>
          <div style={{ marginTop: 56, fontSize: 60, fontWeight: 700, color: "#c8f169", maxWidth: 900 }}>Your next clients, on the radar.</div>
          <div style={{ marginTop: 20, fontSize: 30, color: "#a9c2b9", maxWidth: 860 }}>
            Businesses that need what you sell, with their phone, WhatsApp and a reason to reach out.
          </div>
        </div>
      </div>
    ),
    size,
  );
}
