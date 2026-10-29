# Brand fonts

The brand guideline specifies **Neue Montreal** (English) and **Rubik / Noto Sans Arabic** (Arabic).
Rubik and Noto Sans Arabic are loaded automatically from Google Fonts via `next/font`.

Neue Montreal is a commercial font (Pangram Pangram) and is not bundled. To enable it:

1. Copy `NeueMontreal-Regular.woff2`, `NeueMontreal-Medium.woff2`, `NeueMontreal-Bold.woff2` into this folder.
2. Add to `src/app/globals.css` (above `@theme`):

```css
@font-face { font-family: "Neue Montreal"; src: url("/fonts/NeueMontreal-Regular.woff2") format("woff2"); font-weight: 400; font-display: swap; }
@font-face { font-family: "Neue Montreal"; src: url("/fonts/NeueMontreal-Medium.woff2") format("woff2"); font-weight: 500; font-display: swap; }
@font-face { font-family: "Neue Montreal"; src: url("/fonts/NeueMontreal-Bold.woff2") format("woff2"); font-weight: 700; font-display: swap; }
```

The font stack already lists "Neue Montreal" first, with Inter as the fallback.
