/* static/js/api.js — EduClip fetch wrapper + toast system (no framework) */

const api = {
  async post(path, body) {
    const res = await fetch(`/api/v1${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let message = "Request failed";
      try {
        message = (await res.json()).error?.message ?? message;
      } catch (_) {
        /* keep default */
      }
      throw new Error(message);
    }
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
  setVideo(v) {
    this.video = v;
    if (typeof renderChapters === "function") renderChapters(v.chapters);
    if (typeof renderSummary === "function") renderSummary(v);
  },
};

function showToast(message, type = "info") {
  const wrap = document.getElementById("toastWrap");
  if (!wrap) return;
  const colors = {
    info: "border-slate-700 bg-slate-900",
    success: "border-emerald-500/50 bg-emerald-950/90",
    error: "border-red-500/50 bg-red-950/90",
  };
  const el = document.createElement("div");
  el.className = `px-4 py-3 rounded-xl border text-sm shadow-2xl ${colors[type] ?? colors.info}`;
  el.setAttribute("role", type === "error" ? "alert" : "status");
  el.textContent = message;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}
