/* static/js/api.js — shared EduClip API client (no framework).
   Typed errors, per-request timeouts, retries with backoff, 429/offline
   handling, video polling state machine, toasts, and the render store. */

class ApiError extends Error {
  constructor(message, opts) {
    super(message);
    this.name = "ApiError";
    opts = opts || {};
    this.status = opts.status || 0;
    this.code = opts.code || "REQUEST_FAILED";
    this.retryable = Boolean(opts.retryable);
    this.retryAfterSec = opts.retryAfterSec || 0;
    this.data = opts.data;
  }
}

const api = {
  base: "/api/v1",
  timeoutMs: 30000,
  maxRetries: 2, // retries for transient failures (network / 5xx / timeout)
  pollIntervalMs: 3000,
  pollTimeoutMs: 5 * 60 * 1000, // 5-minute polling timeout

  // UUID v4 without assuming crypto.randomUUID (absent on non-secure contexts).
  newIdempotencyKey() {
    try {
      if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
      }
    } catch (_) {
      /* fall through to Math.random fallback */
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  },

  sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  },

  isOnline() {
    return typeof navigator === "undefined" || navigator.onLine !== false;
  },

  async request(path, opts) {
    opts = opts || {};
    if (!this.isOnline()) {
      throw new ApiError("You're offline. Check your connection and retry.", {
        code: "OFFLINE",
        retryable: true,
      });
    }
    const max = opts.retries !== undefined ? opts.retries : this.maxRetries;
    let lastErr = null;
    for (let attempt = 0; attempt <= max; attempt++) {
      try {
        return await this._fetchOnce(path, opts);
      } catch (err) {
        lastErr = err;
        const transient = err instanceof ApiError && err.retryable;
        // 429s surface immediately (honor Retry-After; UI offers manual Retry).
        const auto = transient && err.code !== "RATE_LIMITED";
        if (!auto || attempt === max) throw err;
        await this.sleep(1000 * 2 ** attempt); // backoff: 1s, 2s
      }
    }
    throw lastErr;
  },

  async _fetchOnce(path, opts) {
    opts = opts || {};
    const method = opts.method || "GET";
    const ctrl = new AbortController();
    const timer = setTimeout(function () {
      ctrl.abort();
    }, this.timeoutMs);
    const headers = {};
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (opts.idempotent) headers["Idempotency-Key"] = this.newIdempotencyKey();
    let res;
    try {
      res = await fetch(this.base + path, {
        method: method,
        signal: ctrl.signal,
        headers: headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      });
    } catch (err) {
      if (err && err.name === "AbortError") {
        throw new ApiError("Request timed out. Please retry.", {
          code: "TIMEOUT",
          retryable: true,
        });
      }
      throw new ApiError("Network error. Check your connection and retry.", {
        code: "NETWORK",
        retryable: true,
      });
    } finally {
      clearTimeout(timer);
    }
    if (res.ok) return res.status === 204 ? null : res.json();

    let parsed = {};
    try {
      parsed = await res.json();
    } catch (_) {
      /* non-JSON error body */
    }
    const errBody = parsed.error || {};
    if (res.status === 429) {
      let retryAfter = 0;
      try {
        retryAfter = Number(res.headers.get("Retry-After")) || 0;
      } catch (_) {
        /* ignore */
      }
      throw new ApiError(
        errBody.message ||
          "Too many requests. Retry" + (retryAfter ? " in " + retryAfter + "s" : " shortly") + ".",
        {
          status: 429,
          code: errBody.code || "RATE_LIMITED",
          retryable: true,
          retryAfterSec: retryAfter,
        }
      );
    }
    throw new ApiError(errBody.message || "Request failed (" + res.status + ").", {
      status: res.status,
      code: errBody.code || "HTTP_" + res.status,
      retryable: res.status >= 500,
    });
  },

  get(path, opts) {
    return this.request(path, Object.assign({}, opts, { method: "GET" }));
  },

  post(path, body, opts) {
    // Every POST carries a fresh Idempotency-Key (safe double-submit).
    return this.request(path, Object.assign({}, opts, { method: "POST", body: body, idempotent: true }));
  },

  // Poll GET /video/<id>/ until ready/failed/timeout. onTick(status, progress) each tick.
  async pollVideo(videoId, opts) {
    opts = opts || {};
    const started = Date.now();
    for (;;) {
      if (opts.signal && opts.signal.aborted) {
        throw new ApiError("Cancelled.", { code: "CANCELLED" });
      }
      const data = await this.get("/video/" + encodeURIComponent(videoId) + "/", { retries: 1 });
      if (data.status === "ready") return data;
      if (data.status === "failed") {
        const msg = (data.error && data.error.message) || "Processing failed. Please try another video.";
        throw new ApiError(msg, {
          code: (data.error && data.error.code) || "PROCESSING_FAILED",
          retryable: false,
          data: data,
        });
      }
      if (Date.now() - started > this.pollTimeoutMs) {
        throw new ApiError("Timed out — the video is taking too long. Try again later.", {
          code: "POLL_TIMEOUT",
          retryable: true,
        });
      }
      if (typeof opts.onTick === "function") opts.onTick(data.status, data.progress);
      await this.sleep(this.pollIntervalMs);
    }
  },
};

const store = {
  video: null,
  // Single hydration point: every section re-renders from one video payload.
  setVideo(v) {
    this.video = v;
    if (typeof destroyCharts === "function") destroyCharts(); // destroy-before-render (charts land later)
    if (typeof renderChapters === "function") renderChapters(v.chapters);
    if (typeof renderSummary === "function") renderSummary(v);
    if (typeof window.renderFlashcards === "function" && v.flashcards !== undefined) {
      window.renderFlashcards(v.flashcards, v.video_id);
    }
  },
};

function showToast(message, type, action) {
  type = type || "info";
  const wrap = document.getElementById("toastWrap");
  if (!wrap) return;
  const colors = {
    info: "border-slate-700 bg-slate-900",
    success: "border-emerald-500/50 bg-emerald-950/90",
    error: "border-red-500/50 bg-red-950/90",
  };
  const icons = { info: "ℹ", success: "✓", error: "⚠" };
  const el = document.createElement("div");
  el.className =
    "px-4 py-3 rounded-xl border text-sm shadow-2xl flex items-center gap-3 " +
    (colors[type] || colors.info);
  el.setAttribute("role", type === "error" ? "alert" : "status");
  const icon = document.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = icons[type] || icons.info;
  el.appendChild(icon);
  const text = document.createElement("span");
  text.textContent = message;
  el.appendChild(text);
  if (action && action.label) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = action.label;
    btn.className = "ml-auto shrink-0 underline underline-offset-2 font-semibold hover:opacity-80 transition";
    btn.addEventListener("click", function () {
      el.remove();
      if (typeof action.onClick === "function") action.onClick();
    });
    el.appendChild(btn);
  }
  wrap.appendChild(el);
  setTimeout(function () {
    el.remove();
  }, 4000);
}
