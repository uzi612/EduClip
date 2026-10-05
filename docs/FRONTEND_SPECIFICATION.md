# EduClip AI — Frontend Specification (Dark-Mode Dashboard)

> **Stack:** Django Templates + Tailwind CSS 3.4 + Vanilla JS (ES2022) + Chart.js 4.x + YouTube IFrame Player API
> **Target:** "$100k-grade" — Linear/Vercel-level polish, 100 Lighthouse performance, WCAG 2.1 AA

---

## Table of Contents

1. [Design Language](#1-design-language)
2. [Tailwind Configuration](#2-tailwind-configuration)
3. [Page & Layout Components](#3-page--layout-components)
4. [Landing / URL Intake View](#4-landing--url-intake-view)
5. [Video Dashboard View](#5-video-dashboard-view)
6. [YouTube IFrame Player API Integration](#6-youtube-iframe-player-api-integration)
7. [Flashcards — 3D Card-Flip](#7-flashcards--3d-card-flip)
8. [Chart.js Visual Analytics](#8-chartjs-visual-analytics)
9. [State Management & API Client](#9-state-management--api-client)
10. [Responsive & Accessibility Rules](#10-responsive--accessibility-rules)
11. [Build & Static Pipeline](#11-build--static-pipeline)

---

## 1. Design Language

### Palette (dark-first)

| Token | Hex | Usage |
|-------|-----|-------|
| `void` | `#030712` | App background (gray-950) |
| `panel` | `#0f172a` | Cards / slate-900 |
| `edge` | `#1e293b` | Borders / slate-800 |
| `accent` | `#8b5cf6` | Primary CTA violet-500 |
| `accent2` | `#06b6d4` | Cyan gradient end |
| `success` | `#10b981` | Ready / progress |
| `warn` | `#f59e0b` | Degraded / fallback |
| `danger` | `#ef4444` | Failed states |
| `ink` | `#f3f4f6` | Primary text gray-100 |
| `muted` | `#9ca3af` | Secondary text gray-400 |

Signature gradient: `from-violet-600 via-purple-600 to-cyan-500` for CTAs, active chapter glow, and chart accents.

### Typography

- **Display:** `Inter` (700/800, tracking-tight) for headlines.
- **Body:** `Inter` 400/500.
- **Mono:** `JetBrains Mono` for timestamps (`0:42`), IDs, JSON debug drawer.
- Scale: `text-5xl` hero → `text-sm` body → `text-xs` mono labels.

### Elevation & Motion

- Cards: `rounded-2xl border border-slate-800 bg-slate-900/70 backdrop-blur-xl shadow-2xl`.
- Micro-interactions: `transition-all duration-200 hover:-translate-y-0.5`.
- Page load: staggered `fade-up` (80ms stagger, 400ms ease-out).
- Respects `prefers-reduced-motion`.

---

## 2. Tailwind Configuration

```javascript
// tailwind.config.js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  darkMode: "class", // <html class="dark"> always in v1
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        void: "#030712",
        panel: "#0f172a",
        edge: "#1e293b",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "flip-in": {
          "0%": { transform: "rotateY(90deg)", opacity: "0" },
          "100%": { transform: "rotateY(0deg)", opacity: "1" },
        },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "fade-up": "fade-up 0.4s ease-out both",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [require("@tailwindcss/line-clamp")],
};
```

```css
/* static/css/base.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

html.dark body { background: #030712; color: #f3f4f6; }
::selection { background: rgba(139, 92, 246, 0.4); }
scrollbar styling:
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 8px; }
```

Dark mode is **default and only** in v1 (`<html class="dark">` hardcoded in `base.html`).

---

## 3. Page & Layout Components

### Base shell (`templates/base.html`)

```html
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}EduClip AI{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="/static/css/base.css" />
  <link rel="stylesheet" href="/static/css/flashcards.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://www.youtube.com/iframe_api"></script>
</head>
<body class="bg-void text-gray-100 font-sans antialiased min-h-screen">
  {% include "partials/navbar.html" %}
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    {% block content %}{% endblock %}
  </main>
  {% include "partials/footer.html" %}
  {% include "partials/toast.html" %}
  <script src="/static/js/api.js"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

### Navbar (`partials/navbar.html`)

- Sticky `backdrop-blur-xl bg-gray-950/80 border-b border-slate-800`.
- Left: gradient logo mark (▶ in violet→cyan rounded square) + `EduClip AI`.
- Right: `How it works` anchor, GitHub link, `Try demo` CTA button.

---

## 4. Landing / URL Intake View

Route: `GET /` — hero + intake form + recent videos grid.

```html
<section class="text-center py-16 animate-fade-up">
  <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 text-violet-300 text-sm">
    ✨ AI-powered video learning
  </div>
  <h1 class="mt-6 text-5xl font-extrabold tracking-tight">
    Turn any <span class="bg-gradient-to-r from-violet-400 to-cyan-400 bg-clip-text text-transparent">YouTube video</span><br/>into a course
  </h1>
  <form id="intakeForm" class="mt-8 max-w-2xl mx-auto flex gap-2 p-2 rounded-2xl border border-slate-800 bg-slate-900/70">
    <input id="youtubeUrl" type="url" required placeholder="Paste YouTube URL… (e.g. youtube.com/watch?v=...)"
      class="flex-1 bg-transparent px-4 py-3 outline-none placeholder:text-gray-500" />
    <button class="px-6 py-3 rounded-xl font-semibold bg-gradient-to-r from-violet-600 to-cyan-500 hover:opacity-90 transition">
      Analyze →
    </button>
  </form>
  <div id="progressWrap" class="hidden mt-6 max-w-2xl mx-auto">
    <div class="flex justify-between text-sm text-gray-400"><span id="progressLabel">Fetching transcript…</span><span id="progressPct">5%</span></div>
    <div class="h-2 mt-2 rounded-full bg-slate-800 overflow-hidden">
      <div id="progressBar" class="h-full w-0 bg-gradient-to-r from-violet-500 to-cyan-400 transition-all duration-500"></div>
    </div>
  </div>
</section>
<section id="recentGrid" class="grid sm:grid-cols-2 lg:grid-cols-3 gap-6 mt-12"></section>
```

Interaction: submit → `POST /api/v1/process-video` → poll → redirect to `/watch/<video_id>/`.

---

## 5. Video Dashboard View

Route: `GET /watch/<video_id>/` — server renders shell with `video_id`; JS hydrates via API.

**Grid (desktop `lg:`):**

```text
┌──────────────────────────────────────────────┐
│ Player (2/3)              │ Chapters (1/3)   │
│ 16:9 iframe + chapter     │ scrollable list  │
│ overlay + seek bar        │ active glow      │
├──────────────────────────────────────────────┤
│ Summary │ Keywords │ Stats (3 cards)         │
├──────────────────────────────────────────────┤
│ Analytics: Bar | Doughnut | Line (Chart.js)  │
├──────────────────────────────────────────────┤
│ Flashcards carousel (flip on click)          │
└──────────────────────────────────────────────┘
```

```html
<div class="grid lg:grid-cols-3 gap-6">
  <div class="lg:col-span-2 space-y-6">
    <div class="rounded-2xl overflow-hidden border border-slate-800 bg-black aspect-video relative">
      <div id="player"></div>
      <div id="chapterToast" class="absolute bottom-4 left-4 px-3 py-1.5 rounded-lg bg-black/70 text-sm hidden"></div>
    </div>
    <div id="summaryCard" class="rounded-2xl border border-slate-800 bg-slate-900/70 p-6"></div>
    <div class="grid md:grid-cols-3 gap-4">
      <canvas id="keywordChart"></canvas>
      <canvas id="chapterChart"></canvas>
      <canvas id="engagementChart"></canvas>
    </div>
  </div>
  <aside class="space-y-3">
    <h2 class="font-semibold text-gray-300">Chapters</h2>
    <div id="chapterList" class="space-y-2 max-h-[600px] overflow-y-auto"></div>
  </aside>
</div>
<div id="flashDeck" class="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-6"></div>
```

Chapter row:

```html
<button data-seek="241" class="chapter-row w-full text-left p-4 rounded-xl border border-slate-800 bg-slate-900/50 hover:border-violet-500/50 transition group">
  <div class="flex justify-between text-sm"><span class="font-mono text-cyan-400">4:01</span><span class="text-gray-500">6:00 min</span></div>
  <div class="font-semibold group-hover:text-violet-300">Calvin Cycle</div>
  <p class="text-sm text-gray-400 line-clamp-2">Carbon fixation in the stroma…</p>
</button>
```

---

## 6. YouTube IFrame Player API Integration

```javascript
// static/js/player.js
let player = null;
let chapters = [];
let currentChapter = -1;

function onYouTubeIframeAPIReady() {
  player = new YT.Player("player", {
    videoId: window.EDUCLIP.youtubeId,
    playerVars: { rel: 0, modestbranding: 1, iv_load_policy: 3 },
    events: { onReady: onPlayerReady, onStateChange: onPlayerStateChange },
  });
}

function onPlayerReady() {
  setInterval(syncChapter, 1000); // chapter highlight + toast
}

function syncChapter() {
  if (!player?.getCurrentTime) return;
  const t = Math.floor(player.getCurrentTime());
  const idx = chapters.findIndex((c) => t >= c.start_sec && t <= c.end_sec);
  if (idx !== currentChapter && idx >= 0) {
    currentChapter = idx;
    document.querySelectorAll(".chapter-row").forEach((el, i) =>
      el.classList.toggle("ring-2", i === idx)
    );
    const toast = document.getElementById("chapterToast");
    toast.textContent = `📖 ${chapters[idx].title}`;
    toast.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toast.classList.add("hidden"), 2500);
  }
}

// Seek from chapter list + flashcards
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-seek]");
  if (btn && player?.seekTo) {
    player.seekTo(Number(btn.dataset.seek), true);
    player.playVideo();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});
```

**Rules:**

- Load IFrame API once (`https://www.youtube.com/iframe_api`); guard `onYouTubeIframeAPIReady` global.
- `playerVars`: `rel:0` (no unrelated), `modestbranding:1`.
- All timestamps use `data-seek="<seconds>"` — single delegated listener.
- Mobile: player sticky-top on scroll (`sticky top-16 z-10` under navbar).

---

## 7. Flashcards — 3D Card-Flip

Custom CSS keyframes (no library) — GPU-friendly `rotateY`.

```css
/* static/css/flashcards.css */
.flash-scene { perspective: 1200px; }
.flash-inner {
  position: relative;
  width: 100%;
  height: 220px;
  transform-style: preserve-3d;
  transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.3, 1.2);
  cursor: pointer;
}
.flash-scene.flipped .flash-inner { transform: rotateY(180deg); }
.flash-face {
  position: absolute;
  inset: 0;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 1.5rem;
  border-radius: 1rem;
  border: 1px solid #1e293b;
}
.flash-front { background: linear-gradient(135deg, #0f172a, #1e1b4b); }
.flash-back {
  background: linear-gradient(135deg, #4c1d95, #0e7490);
  transform: rotateY(180deg);
}
@media (prefers-reduced-motion: reduce) {
  .flash-inner { transition: none; }
}
```

Card markup + JS:

```html
<div class="flash-scene" tabindex="0" role="button" aria-label="Flashcard: click to flip">
  <div class="flash-inner">
    <div class="flash-face flash-front">
      <span class="text-xs font-mono text-cyan-400">0:45 · pigments</span>
      <p class="mt-2 font-semibold">What pigment captures light?</p>
      <span class="mt-4 text-xs text-gray-400">Click to reveal →</span>
    </div>
    <div class="flash-face flash-back">
      <p class="text-sm">Chlorophyll a (+ b and carotenoids).</p>
      <button data-seek="45" class="mt-4 text-xs underline">↗ Jump to 0:45</button>
    </div>
  </div>
</div>
```

```javascript
// static/js/flashcards.js
document.addEventListener("click", (e) => {
  const scene = e.target.closest(".flash-scene");
  if (scene && !e.target.closest("[data-seek]")) scene.classList.toggle("flipped");
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("flash-scene")) {
    e.preventDefault();
    e.target.classList.toggle("flipped");
  }
});
```

Deck extras: shuffle button, `1 / 10` counter, prev/next arrows, keyboard `←/→` navigation.

---

## 8. Chart.js Visual Analytics

Global dark defaults set once:

```javascript
// static/js/charts.js
Chart.defaults.color = "#9ca3af";
Chart.defaults.borderColor = "rgba(30,41,59,0.8)";
Chart.defaults.font.family = "Inter";

const VIOLET = "#8b5cf6", CYAN = "#06b6d4", EMERALD = "#10b981";

function renderAllGraphs(graphs) {
  new Chart(document.getElementById("keywordChart"), {
    type: graphs.keyword_density.type, // 'bar'
    data: {
      labels: graphs.keyword_density.data.labels,
      datasets: graphs.keyword_density.data.datasets.map((d, i) => ({
        ...d,
        backgroundColor: i === 0 ? VIOLET : CYAN,
        borderRadius: 6,
      })),
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "bottom" }, title: { display: true, text: "Keyword density / min" } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });

  new Chart(document.getElementById("chapterChart"), {
    type: "doughnut",
    data: {
      labels: graphs.chapter_duration.data.labels,
      datasets: [{ data: graphs.chapter_duration.data.datasets[0].data,
        backgroundColor: [VIOLET, CYAN, EMERALD, "#f59e0b", "#ef4444"], borderWidth: 0 }],
    },
    options: { cutout: "65%", plugins: { title: { display: true, text: "Time per chapter" } } },
  });

  new Chart(document.getElementById("engagementChart"), {
    type: "line",
    data: {
      labels: graphs.engagement_curve.data.labels,
      datasets: [{ ...graphs.engagement_curve.data.datasets[0],
        borderColor: VIOLET, backgroundColor: "rgba(139,92,246,0.2)", fill: true, tension: 0.4 }],
    },
    options: { plugins: { title: { display: true, text: "Attention curve" } },
      scales: { y: { min: 0, max: 1 } } },
  });
}
```

**Rules:**

- Destroy charts before re-render (`chart.destroy()`).
- Wrap canvases in fixed-height containers (`h-64`) to prevent layout shift.
- Empty state: dashed-border placeholder "Analytics pending…" while `status != ready`.

---

## 9. State Management & API Client

No framework — single `EduClipStore` + `fetch` wrapper:

```javascript
// static/js/api.js
const api = {
  async post(path, body) {
    const res = await fetch(`/api/v1${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).error?.message ?? "Request failed");
    return res.json();
  },
  async get(path) {
    const res = await fetch(`/api/v1${path}`);
    if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
    return res.json();
  },
};

const store = {
  video: null,
  setVideo(v) { this.video = v; renderChapters(v.chapters); renderSummary(v); },
};
```

Toast system (`partials/toast.html`): fixed bottom-right, auto-dismiss 4s, types `info|success|error`.

---

## 10. Responsive & Accessibility Rules

| Breakpoint | Layout |
|------------|--------|
| `<640px` | Single column; sticky player; chapters → horizontal scroll chips; charts stacked |
| `640–1024px` | 2-col flashcards; chapters below player |
| `>1024px` | Full 2/3 + 1/3 dashboard grid |

A11y checklist (must-pass before merge):

- [ ] All interactive elements keyboard-reachable; visible `:focus-visible` ring.
- [ ] Flashcards `role="button"` + `aria-label`; flip on Enter/Space.
- [ ] Canvas has `role="img"` + `aria-label` summary; data table fallback in `<details>`.
- [ ] Contrast ≥4.5:1 body text; timestamps ≥3:1 (decorative mono exempt with label).
- [ ] `prefers-reduced-motion` disables flip/shimmer.

---

## 11. Build & Static Pipeline

```bash
# Dev: Tailwind watch + Django server
npx tailwindcss -i ./static/css/base.css -o ./static/css/output.css --watch &
python manage.py runserver

# Prod (collectstatic → WhiteNoise / S3)
npx tailwindcss -i ./static/css/base.css -o ./static/css/output.css --minify
python manage.py collectstatic --noinput
```

```python
# config/settings/prod.py — static
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
```

Performance budget: initial HTML <100KB, JS <150KB (no bundler in v1), charts lazy-init via `IntersectionObserver`.

---

*Related: `ARCHITECTURE.md` · `API_SPECIFICATION.md` · `DATABASE_DESIGN.md`*
