/* static/js/player.js — YouTube IFrame player + chapter sidebar + timestamp sync.
   Depends on static/js/api.js (api, store, showToast). */

(function () {
  "use strict";

  // Polling cadence lives in api.pollVideo (3s tick, 5-min timeout).
  var SYNC_MS = 1000;

  var player = null;
  var playerReady = false;
  var chapters = [];
  var currentChapter = -1;
  var videoId = null;
  var syncTimer = null;

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

  function fmtStamp(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function videoIdFromPath() {
    var m = window.location.pathname.match(/^\/watch\/([^/]+)\/?$/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  /* ---------- global seek: every timestamp in the app drives playback ---------- */

  window.seekToTimestamp = function (seconds) {
    var t = Math.max(0, Math.floor(Number(seconds) || 0));
    if (player && playerReady && typeof player.seekTo === "function") {
      player.seekTo(t, true);
      if (typeof player.playVideo === "function") player.playVideo();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Single delegated listener for all [data-seek] (chapters now, flashcards later).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-seek]");
    if (btn) window.seekToTimestamp(btn.getAttribute("data-seek"));
  });

  /* ---------- IFrame API (loaded once via base.html) ---------- */

  window.onYouTubeIframeAPIReady = function () {
    initPlayer();
  };

  function initPlayer() {
    if (player || !window.EDUCLIP || !window.EDUCLIP.youtubeId) return; // guard double-init
    if (typeof YT === "undefined" || !YT.Player) return; // API blocked — retry on next tick
    player = new YT.Player("player", {
      videoId: window.EDUCLIP.youtubeId,
      playerVars: { rel: 0, modestbranding: 1, iv_load_policy: 3 },
      events: { onReady: onPlayerReady, onError: onPlayerError },
    });
  }

  function onPlayerReady() {
    playerReady = true;
    if (syncTimer) clearInterval(syncTimer);
    syncTimer = setInterval(syncChapter, SYNC_MS);
  }

  function onPlayerError() {
    showToast("The YouTube player hit an error — the video may be private or embedding-disabled.", "error");
  }

  function syncChapter() {
    if (!playerReady || !player || typeof player.getCurrentTime !== "function") return;
    if (!chapters.length) return;
    var t = Math.floor(player.getCurrentTime());
    var idx = -1;
    for (var i = 0; i < chapters.length; i++) {
      if (t >= chapters[i].start_sec && t <= chapters[i].end_sec) {
        idx = i;
        break;
      }
    }
    if (idx !== currentChapter && idx >= 0) {
      currentChapter = idx;
      var rows = document.querySelectorAll(".chapter-row");
      for (var j = 0; j < rows.length; j++) {
        var active = j === idx;
        rows[j].classList.toggle("ring-2", active);
        rows[j].classList.toggle("ring-violet-500", active);
        rows[j].classList.toggle("border-violet-500/50", active);
        var seekBtn = rows[j].querySelector(".chapter-seek");
        if (seekBtn) {
          if (active) seekBtn.setAttribute("aria-current", "true");
          else seekBtn.removeAttribute("aria-current");
        }
        setRowOpen(rows[j], active); // auto-expand the active chapter (single-open)
      }
      var toast = $("chapterToast");
      if (toast) {
        toast.textContent = "\uD83D\uDCD6 " + chapters[idx].title;
        toast.classList.remove("hidden");
        clearTimeout(toast._t);
        toast._t = setTimeout(function () {
          toast.classList.add("hidden");
        }, 2500);
      }
    }
  }

  /* ---------- chapter sidebar ---------- */

  function skeletonHTML() {
    var out = "";
    for (var i = 0; i < 5; i++) {
      out +=
        '<div class="p-4 rounded-xl border border-slate-800 bg-slate-900/50">' +
        '<div class="h-3 w-24 rounded animate-pulse bg-slate-800"></div>' +
        '<div class="mt-2 h-4 rounded animate-pulse bg-slate-800"></div>' +
        '<div class="mt-2 h-3 w-2/3 rounded animate-pulse bg-slate-800"></div></div>';
    }
    return out;
  }

  function setRowOpen(row, open) {
    row.classList.toggle("open", open);
    var t = row.querySelector(".chapter-toggle");
    if (t) t.setAttribute("aria-expanded", String(open));
  }

  // Accordion toggles (separate from the single [data-seek] listener below).
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest(".chapter-toggle");
    if (!toggle) return;
    var row = toggle.closest(".chapter-row");
    if (!row) return;
    setRowOpen(row, !row.classList.contains("open"));
  });

  function rowHTML(c, i) {
    var dur = Math.max(0, (Number(c.end_sec) || 0) - (Number(c.start_sec) || 0));
    var keywords = (c.keyword_refs || [])
      .map(function (k) {
        return '<span class="px-2 py-0.5 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-300 text-xs font-mono">' + esc(k) + "</span>";
      })
      .join("");
    return (
      '<div class="chapter-row rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden transition">' +
      '<div class="flex items-stretch">' +
      '<button type="button" data-seek="' + esc(c.start_sec) + '" aria-label="Play chapter: ' + esc(c.title || "Untitled chapter") + '" class="chapter-seek flex-1 min-w-0 text-left p-4 hover:bg-white/[0.02] transition group">' +
      '<div class="flex justify-between text-sm"><span class="font-mono text-cyan-400">' +
      esc(fmtStamp(c.start_sec)) +
      '</span><span class="text-gray-500 font-mono">' +
      esc(fmtStamp(dur)) +
      " min</span></div>" +
      '<div class="font-semibold group-hover:text-violet-300 transition">' +
      esc(c.title || "Untitled chapter") +
      "</div>" +
      (c.summary
        ? '<p class="chapter-preview text-sm text-gray-400 line-clamp-2 mt-1">' + esc(c.summary) + "</p>"
        : "") +
      "</button>" +
      '<button type="button" class="chapter-toggle shrink-0 px-3 text-gray-500 hover:text-gray-100 transition" aria-expanded="false" aria-controls="chapter-detail-' + i + '" aria-label="Expand chapter details">' +
      '<svg class="chapter-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>' +
      "</button></div>" +
      '<div id="chapter-detail-' + i + '" class="chapter-detail"><div>' +
      '<div class="px-4 pb-4 pt-1 space-y-3 border-t border-slate-800/70">' +
      (c.summary ? '<p class="text-sm text-gray-300 leading-relaxed">' + esc(c.summary) + "</p>" : "") +
      (keywords ? '<div class="flex flex-wrap gap-1.5">' + keywords + "</div>" : "") +
      '<div class="flex items-center justify-between gap-2">' +
      '<span class="text-xs font-mono text-gray-500">' + esc(fmtStamp(c.start_sec)) + " → " + esc(fmtStamp(c.end_sec)) + "</span>" +
      '<button type="button" data-seek="' + esc(c.start_sec) + '" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gradient-to-r from-violet-600 to-cyan-500 hover:opacity-90 transition whitespace-nowrap">▶ Play from ' + esc(fmtStamp(c.start_sec)) + "</button>" +
      "</div></div></div></div></div>"
    );
  }

  window.renderChapters = function (list) {
    chapters = (list || []).slice().sort(function (a, b) {
      return (a.start_sec || 0) - (b.start_sec || 0);
    });
    currentChapter = -1;
    var wrap = $("chapterList");
    var count = $("chapterCount");
    if (count) count.textContent = chapters.length ? chapters.length + " chapters" : "";
    if (!wrap) return;
    if (!chapters.length) {
      wrap.innerHTML = '<p class="text-sm text-gray-500 rounded-xl border border-dashed border-slate-800 p-6 text-center">No chapters yet for this video.</p>';
      return;
    }
    wrap.innerHTML = chapters
      .map(function (c, i) {
        return rowHTML(c, i);
      })
      .join("");
    var first = wrap.querySelector(".chapter-row");
    if (first) setRowOpen(first, true); // first chapter expanded by default
  };

  function renderHeader(v) {
    var title = $("videoTitle");
    var meta = $("videoMeta");
    if (title) title.textContent = v.title || "Untitled video";
    if (meta) {
      var bits = [];
      if (v.channel) bits.push(v.channel);
      if (v.duration_sec) bits.push(fmtStamp(v.duration_sec));
      if (v.status && v.status !== "ready") bits.push(v.status);
      meta.textContent = bits.join(" · ");
    }
    document.title = (v.title || "Watch") + " — EduClip AI";
  }

  function showFatal(msg) {
    var err = $("pageError");
    var wrap = $("watchWrap");
    if (err) {
      err.classList.remove("hidden");
      var m = $("pageErrorMsg");
      if (m && msg) m.textContent = msg;
    }
    if (wrap) wrap.classList.add("hidden");
  }

  function hideFatal() {
    var err = $("pageError");
    var wrap = $("watchWrap");
    if (err) err.classList.add("hidden");
    if (wrap) wrap.classList.remove("hidden");
  }

  /* ---------- boot: fetch video, poll while processing, init player ---------- */

  function boot() {
    var list = $("chapterList");
    if (!list) return; // not the watch page
    videoId = videoIdFromPath();
    if (!videoId) {
      showFatal("Missing video id in the URL.");
      return;
    }
    window.EDUCLIP = window.EDUCLIP || {};
    list.innerHTML = skeletonHTML();
    fetchVideo();
    var retry = $("retryBtn");
    if (retry) retry.addEventListener("click", fetchVideo);
  }

  function hydrate(data) {
    renderHeader(data);
    store.setVideo(data); // -> chapters (+ flashcards when present) via the store
    window.EDUCLIP.youtubeId = data.youtube_id;
    initPlayer();
    if (data.flashcards === undefined && typeof window.renderFlashcards === "function") {
      // Payload had no cards — fall back to the dedicated endpoint.
      window.renderFlashcards(undefined, data.video_id);
    }
  }

  function fetchVideo() {
    hideFatal();
    api
      .get("/video/" + encodeURIComponent(videoId) + "/")
      .then(function (data) {
        if (data.status === "ready") {
          hydrate(data);
          return;
        }
        if (data.status === "failed") {
          var msg =
            (data.error && data.error.message) || "Processing failed. Please try another video.";
          showFatal(msg);
          return;
        }
        // Still processing: render what we have, then poll to ready.
        renderHeader(data);
        store.setVideo(data);
        return api.pollVideo(videoId, {}).then(hydrate);
      })
      .catch(function (err) {
        // Offline / 429 / timeout / failed — message plus the Retry button.
        showFatal((err && err.message) || "Could not load this video. The API may not be up yet.");
      });
  }

  // If the IFrame API already loaded before this script ran, init directly.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot();
      initPlayer();
    });
  } else {
    boot();
    initPlayer();
  }
})();
