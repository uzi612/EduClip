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
  // Rich text lives in api.js; fall back to plain escaping if it failed to load.
  var RT = typeof richText === "function" ? richText : esc;

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

  function fmtDurLen(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    if (sec < 60) return sec + "s";
    var mins = Math.round(sec / 60);
    return mins + (mins === 1 ? " min" : " mins");
  }

  function videoIdFromPath() {
    var m = window.location.pathname.match(/^\/watch\/([^/]+)\/?$/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  /* ---------- global seek: every timestamp in the app drives playback ---------- */

  window.getPlayerTime = function () {
    if (player && playerReady && typeof player.getCurrentTime === "function") {
      try {
        return Math.floor(player.getCurrentTime());
      } catch (_) {
        return 0;
      }
    }
    return 0;
  };

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
        '<div class="skel h-3 w-24"></div>' +
        '<div class="skel mt-2 h-4"></div>' +
        '<div class="skel mt-2 h-3 w-2/3"></div></div>';
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
      esc(fmtDurLen(dur)) +
      "</span></div>" +
      '<div class="font-semibold group-hover:text-violet-300 transition">' +
      esc(c.title || "Untitled chapter") +
      "</div>" +
      (c.summary
        ? '<p class="chapter-preview text-sm text-gray-400 line-clamp-2 mt-1">' + RT(c.summary) + "</p>"
        : "") +
      "</button>" +
      '<button type="button" class="chapter-toggle shrink-0 px-3 text-gray-500 hover:text-gray-100 transition" aria-expanded="false" aria-controls="chapter-detail-' + i + '" aria-label="Expand chapter details">' +
      '<svg class="chapter-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>' +
      "</button></div>" +
      '<div id="chapter-detail-' + i + '" class="chapter-detail"><div>' +
      '<div class="px-4 pb-4 pt-1 space-y-3 border-t border-slate-800/70">' +
      (c.summary ? '<div class="text-sm text-gray-300 leading-relaxed rich-text">' + RT(c.summary) + "</div>" : "") +
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
    // Shared read-only for cross-links (charts annotations, legend seeks).
    window.EDUCLIP = window.EDUCLIP || {};
    window.EDUCLIP.chapters = chapters;
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

  window.renderSummary = function (v) {
    var card = $("summaryCard");
    var body = $("summaryBody");
    if (!card || !body) return;
    if (v && v.summary) {
      body.innerHTML = RT(v.summary);
      card.classList.remove("hidden");
    } else {
      card.classList.add("hidden");
    }
  };

  function statPill(label, value) {
    return (
      '<span class="inline-flex items-baseline gap-1.5 px-3 py-1.5 rounded-full border border-slate-800 bg-slate-900/70 text-sm">' +
      '<span class="font-bold text-gray-100">' + esc(value) + "</span>" +
      '<span class="text-gray-500 text-xs">' + esc(label) + "</span></span>"
    );
  }

  function renderTopStrips(v) {
    var stats = $("statStrip");
    var strip = $("keywordStrip");
    var preview = v && v.analytics_preview;
    if (stats) {
      if (preview) {
        stats.innerHTML =
          statPill(preview.reading_minutes, "min read") +
          statPill(preview.chapter_count, "chapters") +
          statPill((v.keywords || []).length, "keywords");
        stats.classList.remove("hidden");
      } else {
        stats.classList.add("hidden");
      }
    }
    if (strip) {
      var kws = ((v && v.keywords) || []).slice(0, 8);
      if (!kws.length) {
        strip.classList.add("hidden");
        return;
      }
      strip.innerHTML = kws
        .map(function (k) {
          return (
            '<button type="button" data-keyword="' + esc(k.term) + '" title="' +
            esc(k.count + " mentions · score " + k.score) + '"' +
            ' class="px-3 py-1.5 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-300 text-xs font-mono hover:border-cyan-400/60 transition">' +
            esc(k.term) + " · " + esc(k.count) + "</button>"
          );
        })
        .join("");
      strip.classList.remove("hidden");
    }
  }

  // Keyword pills highlight every chapter mentioning the term.
  document.addEventListener("click", function (e) {
    var pill = e.target.closest("[data-keyword]");
    if (!pill) return;
    var term = (pill.getAttribute("data-keyword") || "").toLowerCase();
    if (!term) return;
    var hits = 0;
    var rows = document.querySelectorAll(".chapter-row");
    for (var i = 0; i < rows.length; i++) {
      var hay = (rows[i].textContent || "").toLowerCase();
      var on = term && hay.indexOf(term) !== -1;
      rows[i].classList.toggle("ring-2", on);
      rows[i].classList.toggle("ring-cyan-400", on);
      if (on) hits++;
    }
    if (typeof showToast === "function") {
      showToast(hits ? hits + " chapter(s) mention “" + term + "”." : "No chapter mentions “" + term + "”.", "info");
    }
  });

  function renderHeader(v) {
    var title = $("videoTitle");
    var meta = $("videoMeta");
    renderTopStrips(v);
    if (title) title.textContent = v.title || "Untitled video";
    if (meta) {
      var bits = [];
      if (v.channel) bits.push(v.channel);
      if (v.duration_sec) bits.push(fmtStamp(v.duration_sec));
      if (v.status && v.status !== "ready") bits.push(v.status);
      meta.textContent = bits.join(" · ");
    }
    document.title = (v.title || "Watch") + " — EduClip AI";
    var banner = $("degradedBanner");
    if (banner) {
      if (v.degraded) {
        banner.classList.remove("hidden");
        var detail = $("degradedDetail");
        if (detail) {
          detail.textContent =
            v.transcript_source === "whisper_fallback"
              ? "audio transcription fallback was used; timestamps may be approximate."
              : "a fallback path was used; some sections may be approximate.";
        }
      } else {
        banner.classList.add("hidden");
      }
    }
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
    window.EDUCLIP = window.EDUCLIP || {};
    window.EDUCLIP.video = data; // stash for notes/export modules
    store.setVideo(data); // -> chapters (+ flashcards when present) via the store
    if (typeof window.renderCharts === "function") {
      window.renderCharts(data.graphs, data.video_id);
    }
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
