/* static/js/landing.js — intake validation, submit → poll → redirect, recent grid.
   Depends on static/js/api.js (api, showToast). */

(function () {
  "use strict";

  var YOUTUBE_RE = /(?:v=|youtu\.be\/|shorts\/)([A-Za-z0-9_-]{11})/;
  // Polling cadence lives in api.pollVideo (3s tick, 5-min timeout).

  var LABELS = {
    queued: "Queued…",
    processing: "Fetching transcript…",
    analyzing: "Analyzing with AI…",
    ready: "Ready!",
  };

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtDur(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function extractId(url) {
    var m = YOUTUBE_RE.exec(url || "");
    return m ? m[1] : null;
  }

  /* ---------- intake ---------- */

  var form = $("intakeForm");
  var input = $("youtubeUrl");
  var urlError = $("urlError");
  var submitBtn = $("submitBtn");
  var submitLabel = $("submitLabel");
  var submitSpinner = $("submitSpinner");
  var progressWrap = $("progressWrap");
  var progressLabel = $("progressLabel");
  var progressPct = $("progressPct");
  var progressBar = $("progressBar");

  function showError(msg) {
    if (!urlError) return;
    urlError.textContent = msg;
    urlError.classList.remove("hidden");
    if (input) {
      input.setAttribute("aria-invalid", "true");
      input.focus();
    }
  }

  function clearError() {
    if (urlError) {
      urlError.textContent = "";
      urlError.classList.add("hidden");
    }
    if (input) input.removeAttribute("aria-invalid");
  }

  function setBusy(busy) {
    if (submitBtn) submitBtn.disabled = busy;
    if (submitLabel) submitLabel.classList.toggle("hidden", busy);
    if (submitSpinner) {
      submitSpinner.classList.toggle("hidden", !busy);
      submitSpinner.classList.toggle("inline-flex", busy);
    }
  }

  function setProgress(status, progress) {
    var pct = Math.round(Math.max(0, Math.min(1, Number(progress) || 0)) * 100);
    if (progressWrap) progressWrap.classList.remove("hidden");
    if (progressLabel) progressLabel.textContent = LABELS[status] || status;
    if (progressPct) progressPct.textContent = pct + "%";
    if (progressBar) progressBar.style.width = pct + "%";
  }

  function resetProgress() {
    if (progressWrap) progressWrap.classList.add("hidden");
    if (progressBar) progressBar.style.width = "0%";
  }

  function submitError(err) {
    resetProgress();
    var code = err && err.code;
    var resubmit = function () {
      if (form && typeof form.requestSubmit === "function") form.requestSubmit();
    };
    // Terminal failures get a focus-trapped modal with Retry; the rest get toasts.
    if ((code === "PROCESSING_FAILED" || code === "POLL_TIMEOUT") && typeof window.showModal === "function") {
      window.showModal({
        title: code === "POLL_TIMEOUT" ? "Taking too long" : "Processing failed",
        message: (err && err.message) || "Something went wrong.",
        retryLabel: "Retry",
        onRetry: resubmit,
      });
      return;
    }
    var retryable = Boolean(err && err.retryable);
    showToast(
      (err && err.message) || "Something went wrong.",
      "error",
      retryable ? { label: "Retry", onClick: resubmit } : undefined
    );
  }

  function onSubmit(e) {
    e.preventDefault();
    clearError();
    var url = (input.value || "").trim();
    if (url.length > 500) {
      showError("URL is too long (max 500 characters).");
      return;
    }
    if (!extractId(url)) {
      showError("Not a valid YouTube URL. Expected youtube.com/watch?v=... or youtu.be/...");
      return;
    }
    setBusy(true);
    setProgress("processing", 0.05);
    api
      .post("/process-video", { youtube_url: url })
      .then(function (data) {
        if (data.status === "ready") return data;
        return api.pollVideo(data.video_id, {
          onTick: function (status, progress) {
            setProgress(status, progress);
          },
        });
      })
      .then(function (data) {
        if (!data) return;
        setProgress("ready", 1);
        window.location.href = "/watch/" + data.video_id + "/";
      })
      .catch(submitError)
      .then(function () {
        setBusy(false);
      });
  }

  if (form) {
    form.addEventListener("submit", onSubmit);
    if (input) input.addEventListener("input", clearError);
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-demo]");
    if (!btn || !input || !form) return;
    input.value = btn.getAttribute("data-demo");
    clearError();
    input.focus();
  });

  /* ---------- recent grid ---------- */

  var STATUS_BADGE = {
    ready: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    processing: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    analyzing: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    queued: "bg-slate-500/15 text-slate-300 border-slate-500/30",
    failed: "bg-red-500/15 text-red-300 border-red-500/30",
  };

  function skeletonHTML() {
    var out = "";
    for (var i = 0; i < 6; i++) {
      out +=
        '<div class="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden">' +
        '<div class="skel skel-aspect-video"></div>' +
        '<div class="p-4 space-y-2"><div class="skel h-4"></div>' +
        '<div class="skel h-3 w-2/3"></div></div></div>';
    }
    return out;
  }

  function cardHTML(v) {
    var badge = STATUS_BADGE[v.status] || STATUS_BADGE.queued;
    var thumb =
      v.thumbnail ||
      (v.youtube_id ? "https://i.ytimg.com/vi/" + v.youtube_id + "/hqdefault.jpg" : "");
    return (
      '<a href="/watch/' + esc(v.video_id) + '/" class="group rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden hover:border-violet-500/50 transition">' +
      '<div class="relative aspect-video bg-black">' +
      (thumb
        ? '<img src="' + esc(thumb) + '" alt="" loading="lazy" class="w-full h-full object-cover group-hover:opacity-90 transition" />'
        : "") +
      '<span class="absolute bottom-2 right-2 px-1.5 py-0.5 rounded-md bg-black/70 text-xs font-mono text-gray-200">' +
      esc(fmtDur(v.duration_sec)) +
      "</span></div>" +
      '<div class="p-4"><p class="font-semibold line-clamp-2 group-hover:text-violet-300 transition">' +
      esc(v.title || "Untitled video") +
      "</p>" +
      '<div class="mt-2"><span class="inline-block px-2 py-0.5 rounded-full border text-xs ' + badge + '">' +
      esc(v.status || "queued") +
      "</span></div></div></a>"
    );
  }

  function loadRecent() {
    var grid = $("recentGrid");
    var empty = $("recentEmpty");
    var count = $("recentCount");
    if (!grid) return;
    grid.innerHTML = skeletonHTML();
    api
      .get("/videos/?page=1&page_size=9")
      .then(function (data) {
        var items = (data && data.items) || [];
        if (!items.length) {
          grid.innerHTML = "";
          if (empty) empty.classList.remove("hidden");
          if (count) count.textContent = "";
          return;
        }
        if (empty) empty.classList.add("hidden");
        grid.innerHTML = items.map(cardHTML).join("");
        if (count) count.textContent = items.length + " shown";
      })
      .catch(function () {
        // List endpoint not implemented yet (backend A4) — show empty state, not an error.
        grid.innerHTML = "";
        if (empty) empty.classList.remove("hidden");
        if (count) count.textContent = "";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadRecent);
  } else {
    loadRecent();
  }
})();
