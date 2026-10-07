/* static/js/player.js — YouTube IFrame player + chapter sidebar + timestamp sync.
   Depends on static/js/api.js (api, store, showToast). */

(function () {
  "use strict";

  var POLL_MS = 3000;
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
        rows[j].classList.toggle("ring-2", j === idx);
        rows[j].classList.toggle("ring-violet-500", j === idx);
        rows[j].classList.toggle("border-violet-500/50", j === idx);
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

  function rowHTML(c) {
    var dur = Math.max(0, (Number(c.end_sec) || 0) - (Number(c.start_sec) || 0));
    return (
      '<button type="button" data-seek="' + esc(c.start_sec) + '" class="chapter-row w-full text-left p-4 rounded-xl border border-slate-800 bg-slate-900/50 hover:border-violet-500/50 transition group">' +
      '<div class="flex justify-between text-sm"><span class="font-mono text-cyan-400">' +
      esc(fmtStamp(c.start_sec)) +
      '</span><span class="text-gray-500 font-mono">' +
      esc(fmtStamp(dur)) +
      " min</span></div>" +
      '<div class="font-semibold group-hover:text-violet-300 transition">' +
      esc(c.title || "Untitled chapter") +
      "</div>" +
      (c.summary
        ? '<p class="text-sm text-gray-400 line-clamp-2 mt-1">' + esc(c.summary) + "</p>"
        : "") +
      "</button>"
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
    wrap.innerHTML = chapters.length
      ? chapters.map(rowHTML).join("")
      : '<p class="text-sm text-gray-500 rounded-xl border border-dashed border-slate-800 p-6 text-center">No chapters yet for this video.</p>';
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

  function fetchVideo() {
    hideFatal();
    api
      .get("/video/" + encodeURIComponent(videoId) + "/")
      .then(function (data) {
        if (data.status === "failed") {
          var msg =
            (data.error && data.error.message) || "Processing failed. Please try another video.";
          showFatal(msg);
          return;
        }
        renderHeader(data);
        store.setVideo(data); // -> renderChapters via api.js store hook
        if (data.status === "ready") {
          window.EDUCLIP.youtubeId = data.youtube_id;
          initPlayer();
          return;
        }
        // Still processing: keep skeletons, poll until terminal state.
        setTimeout(fetchVideo, POLL_MS);
      })
      .catch(function (err) {
        showFatal(err.message || "Could not load this video. The API may not be up yet.");
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
