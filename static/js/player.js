/* static/js/player.js — YouTube IFrame player + chapter sidebar + timestamp sync.
   Depends on static/js/api.js (api, store, showToast). */

(function () {
  "use strict";

  // Polling cadence lives in api.pollVideo (3s tick, 5-min timeout).
  var SYNC_MS = 1000;

  var player = null;
  var playerReady = false;
  var chapters = [];
  var transcript = [];
  var currentChapter = -1;
  var currentLine = -1;
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

  function fmtDurLen(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    if (sec < 60) return sec + "s";
    var mins = Math.round(sec / 60);
    return mins + (mins === 1 ? " min" : " mins");
  }

  // Rich text lives in api.js; fall back to plain escaping if it failed to load.
  var RT = typeof richText === "function" ? richText : esc;

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

  /* ---------- study aids: done checklist + resume (localStorage, per video) ---------- */

  function doneKey() { return "educlip-done-" + (videoId || "home"); }
  function posKey() { return "educlip-pos-" + (videoId || "home"); }

  function getDone() {
    try {
      var raw = localStorage.getItem(doneKey());
      var arr = raw ? JSON.parse(raw) : [];
      var set = {};
      for (var i = 0; i < arr.length; i++) set[arr[i]] = true;
      return set;
    } catch (_) { return {}; }
  }

  function saveDone(set) {
    try {
      var arr = Object.keys(set).filter(function (k) { return set[k]; });
      localStorage.setItem(doneKey(), JSON.stringify(arr));
    } catch (_) { /* private mode */ }
  }

  var lastPosSave = 0;

  function savePos(t) {
    try { localStorage.setItem(posKey(), String(Math.floor(t))); }
    catch (_) { /* private mode */ }
  }

  function readPos() {
    try { return Math.max(0, Math.floor(Number(localStorage.getItem(posKey())) || 0)); }
    catch (_) { return 0; }
  }

  function paintProgress() {
    var bar = $("chapterProgress");
    if (!bar || !chapters.length) return;
    var done = getDone();
    var n = 0;
    for (var i = 0; i < chapters.length; i++) if (done[i]) n++;
    bar.style.width = Math.round((n / chapters.length) * 100) + "%";
  }

  function copyText(text, okMsg) {
    function done() { showToast(okMsg, "success"); }
    if (text == null || !text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { showToast("Copy failed in this browser.", "error"); });
      return;
    }
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      done();
    } catch (_) { showToast("Copy failed in this browser.", "error"); }
  }

  // Extractive takeaways: first 3 sentences of the existing summary (no LLM).
  function takeaways(summary) {
    var parts = String(summary || "").split(/(?<=[.!?])\s+/);
    var out = [];
    for (var i = 0; i < parts.length && out.length < 3; i++) {
      var s = parts[i].trim();
      if (s.length > 12) out.push(s);
    }
    return out;
  }

  function renderBrief(v) {
    var bar = $("briefBar");
    if (!bar) return;
    var keys = (v && v.keywords) || [];
    var hasSummary = Boolean(v && v.summary);
    if (!hasSummary && !keys.length) { bar.classList.add("hidden"); return; }
    bar.classList.remove("hidden");
    var list = $("briefTakeaways");
    if (list) {
      var items = takeaways(v.summary);
      list.innerHTML = items.map(function (s) {
        return "<li class='flex gap-2'><span class='text-violet-600 dark:text-violet-300 font-bold' aria-hidden='true'>→</span><span>" + esc(s) + "</span></li>";
      }).join("") || "<li class='text-gray-500'>Summary available below.</li>";
    }
    var chips = $("keywordChips");
    if (chips) {
      chips.innerHTML = keys.slice(0, 8).map(function (k) {
        return '<button type="button" data-kwseek="' + esc(k.term) + '" class="px-2.5 py-1 rounded-full border border-slate-300 dark:border-slate-700 bg-white/60 dark:bg-slate-900/50 text-xs text-slate-600 dark:text-gray-300 hover:border-violet-500/60 hover:text-slate-900 dark:hover:text-white transition">' +
          esc(k.term) + ' <span class="font-mono opacity-70">×' + esc(k.count) + "</span></button>";
      }).join("");
    }
    var start = $("briefStart");
    if (start) {
      var preview = v && v.analytics_preview;
      var n = (preview && preview.chapter_count) || (v.chapters || []).length;
      if (n > 1) {
        start.classList.remove("hidden");
        var best = 0, bestScore = -1;
        ((v && v.chapters) || []).forEach(function (c, i) {
          var s = ((c.keyword_refs || []).length * 10) + ((c.summary || "").length / 100);
          if (s > bestScore) { bestScore = s; best = i; }
        });
        start.textContent = "Start here → " + fmtStamp((((v.chapters || [])[best] || {}).start_sec) || 0);
        start.onclick = function () {
          var c = (v.chapters || [])[best];
          if (c) window.seekToTimestamp(c.start_sec);
        };
      } else start.classList.add("hidden");
    }
    var copyBtn = $("briefCopy");
    if (copyBtn) copyBtn.classList.toggle("hidden", !hasSummary);
  }

  function syncChapter() {
    if (!playerReady || !player || typeof player.getCurrentTime !== "function") return;
    if (!chapters.length) return;
    var t = Math.floor(player.getCurrentTime());
    if (t - lastPosSave > 10 || t < lastPosSave) { lastPosSave = t; savePos(t); }
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
        toast.textContent = chapters[idx].title;
        toast.classList.remove("hidden");
        clearTimeout(toast._t);
        toast._t = setTimeout(function () {
          toast.classList.add("hidden");
        }, 2500);
      }
    }
    if (transcript.length) {
      var line = -1;
      for (var k = 0; k < transcript.length; k++) {
        var st = Number(transcript[k].start) || 0;
        var du = Number(transcript[k].duration) || 0;
        if (t >= Math.floor(st) && t < Math.floor(st) + Math.max(1, Math.ceil(du))) { line = k; break; }
      }
      if (line !== currentLine) { currentLine = line; paintTranscriptActive(); }
    }
  }

  /* ---------- chapter sidebar ---------- */

  function skeletonHTML() {
    var out = "";
    for (var i = 0; i < 5; i++) {
      out +=
        '<div class="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50">' +
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
        return '<span class="px-2 py-0.5 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 text-xs font-mono">' + esc(k) + "</span>";
      })
      .join("");
    return (
      '<div class="chapter-row rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 overflow-hidden shadow-sm hover:shadow-md transition">' +
      '<div class="flex items-stretch">' +
      '<button type="button" data-seek="' + esc(c.start_sec) + '" aria-label="Play chapter: ' + esc(c.title || "Untitled chapter") + '" class="chapter-seek flex-1 min-w-0 text-left p-4 hover:bg-violet-500/5 dark:hover:bg-white/[0.02] transition group">' +
      '<div class="flex justify-between text-sm"><span class="font-mono text-cyan-700 dark:text-cyan-400">' +
      esc(fmtStamp(c.start_sec)) +
      '</span><span class="text-gray-500 font-mono">' +
      esc(fmtDurLen(dur)) +
      "</span></div>" +
      '<div class="chapter-title font-semibold text-slate-900 dark:text-gray-100 group-hover:text-violet-700 dark:group-hover:text-violet-300 transition">' +
      esc(c.title || "Untitled chapter") +
      "</div>" +
      (c.summary
        ? '<p class="chapter-preview text-sm text-slate-500 dark:text-gray-400 line-clamp-2 mt-1">' + RT(c.summary) + "</p>"
        : "") +
      "</button>" +
      '<button type="button" data-done="' + i + '" aria-pressed="false" aria-label="Mark chapter done" class="chapter-done shrink-0 self-center w-7 h-7 mr-1 rounded-full border border-slate-300 dark:border-slate-700 text-gray-500 hover:border-emerald-500/60 hover:text-emerald-600 dark:hover:text-emerald-300 transition text-sm">✓</button>' +
      '<button type="button" class="chapter-toggle shrink-0 px-3 text-gray-500 hover:text-slate-900 dark:hover:text-gray-100 transition" aria-expanded="false" aria-controls="chapter-detail-' + i + '" aria-label="Expand chapter details">' +
      '<svg class="chapter-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>' +
      "</button></div>" +
      '<div id="chapter-detail-' + i + '" class="chapter-detail"><div>' +
      '<div class="px-4 pb-4 pt-1 space-y-3 border-t border-slate-200 dark:border-slate-800/70">' +
      (c.summary ? '<div class="text-sm text-slate-700 dark:text-gray-300 leading-relaxed rich-text">' + RT(c.summary) + "</div>" : "") +
      (keywords ? '<div class="flex flex-wrap gap-1.5">' + keywords + "</div>" : "") +
      '<div class="flex items-center justify-between gap-2">' +
      '<span class="text-xs font-mono text-gray-500">' + esc(fmtStamp(c.start_sec)) + " → " + esc(fmtStamp(c.end_sec)) + "</span>" +
      '<button type="button" data-seek="' + esc(c.start_sec) + '" class="px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-gradient-to-r from-violet-600 to-cyan-500 hover:opacity-90 transition whitespace-nowrap">▶ Play from ' + esc(fmtStamp(c.start_sec)) + "</button>" +
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
      wrap.innerHTML = '<p class="text-sm text-gray-500 rounded-xl border border-dashed border-slate-300 dark:border-slate-800 p-6 text-center">No chapters yet for this video.</p>';
      return;
    }
    wrap.innerHTML = chapters
      .map(function (c, i) {
        return rowHTML(c, i);
      })
      .join("");
    var done = getDone();
    var rows = wrap.querySelectorAll(".chapter-row");
    for (var r = 0; r < rows.length; r++) {
      if (done[r]) {
        rows[r].classList.add("done");
        var b = rows[r].querySelector("[data-done]");
        if (b) { b.setAttribute("aria-pressed", "true"); b.classList.add("done-on"); }
      }
    }
    paintProgress();
    var first = wrap.querySelector(".chapter-row");
    if (first) setRowOpen(first, true); // first chapter expanded by default
  };

  // Done toggles + keyword-seek (separate from the single [data-seek] listener).
  document.addEventListener("click", function (e) {
    var doneBtn = e.target.closest ? e.target.closest("[data-done]") : null;
    if (doneBtn) {
      var row = doneBtn.closest(".chapter-row");
      var rows = Array.prototype.slice.call(document.querySelectorAll("#chapterList .chapter-row"));
      var idx = rows.indexOf(row);
      if (idx >= 0) {
        var set = getDone();
        if (set[idx]) delete set[idx];
        else set[idx] = true;
        saveDone(set);
        row.classList.toggle("done", Boolean(set[idx]));
        doneBtn.setAttribute("aria-pressed", String(Boolean(set[idx])));
        doneBtn.classList.toggle("done-on", Boolean(set[idx]));
        paintProgress();
      }
      return;
    }
    var kw = e.target.closest ? e.target.closest("[data-kwseek]") : null;
    if (kw) {
      var term = (kw.getAttribute("data-kwseek") || "").toLowerCase();
      if (!term) return;
      var found = -1;
      for (var i = 0; i < chapters.length; i++) {
        var c = chapters[i];
        var hay = ((c.title || "") + " " + (c.summary || "") + " " + ((c.keyword_refs || []).join(" "))).toLowerCase();
        if (hay.indexOf(term) >= 0) { found = i; break; }
      }
      if (found >= 0) window.seekToTimestamp(chapters[found].start_sec);
      else showToast("No chapter mentions “" + term + "” directly — try the chapter list.", "info");
    }
  });

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

  function statPill(value, label) {
    return (
      '<span class="inline-flex items-baseline gap-1.5 px-3 py-1.5 rounded-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/70 text-sm shadow-sm">' +
      '<span class="font-bold text-slate-900 dark:text-gray-100">' + esc(value) + "</span>" +
      '<span class="text-gray-500 text-xs">' + esc(label) + "</span></span>"
    );
  }

  function renderTopStrips(v) {
    var stats = $("statStrip");
    var preview = v && v.analytics_preview;
    if (!stats) return;
    if (preview) {
      stats.innerHTML =
        statPill(preview.reading_minutes, "min read") +
        statPill(preview.chapter_count, "chapters") +
        statPill(v.flashcard_count || 0, "flashcards");
      stats.classList.remove("hidden");
    } else {
      stats.classList.add("hidden");
    }
  }

  /* ---------- transcript: searchable click-to-seek lines ---------- */

  function transcriptRow(s, i) {
    return '<button type="button" data-seek="' + esc(Math.floor(s.start || 0)) + '" data-tline="' + i + '"' +
      ' class="transcript-row w-full flex gap-3 text-left px-3 py-2 rounded-lg text-sm border border-transparent hover:border-violet-300/60 hover:bg-violet-50 dark:hover:bg-violet-500/10 transition">' +
      '<span class="font-mono text-cyan-600 dark:text-cyan-400 shrink-0">' + esc(fmtStamp(s.start)) + "</span>" +
      '<span class="text-slate-700 dark:text-gray-300">' + esc(s.text || "") + "</span></button>";
  }

  function paintTranscript(filter) {
    var list = $("transcriptList");
    var pending = $("transcriptPending");
    var count = $("transcriptCount");
    if (!list) return;
    var q = (filter || "").toLowerCase().trim();
    var rows = transcript.map(function (s, i) { return { s: s, i: i }; });
    if (q) rows = rows.filter(function (r) { return (r.s.text || "").toLowerCase().indexOf(q) >= 0; });
    if (!transcript.length) {
      list.innerHTML = "";
      if (pending) pending.classList.remove("hidden");
      if (count) count.textContent = "";
      return;
    }
    if (pending) pending.classList.add("hidden");
    if (count) count.textContent = q ? rows.length + " / " + transcript.length + " lines" : transcript.length + " lines";
    list.innerHTML = rows.length
      ? rows.map(function (r) { return transcriptRow(r.s, r.i); }).join("")
      : '<p class="text-sm text-gray-500 p-4 text-center">No lines match “' + esc(filter) + ".”</p>";
    paintTranscriptActive();
  }

  function paintTranscriptActive() {
    var rows = document.querySelectorAll ? document.querySelectorAll(".transcript-row") : [];
    for (var k = 0; k < rows.length; k++) {
      var on = Number(rows[k].getAttribute("data-tline")) === currentLine;
      rows[k].classList.toggle("bg-violet-500/15", on);
    }
  }

  window.renderTranscript = function (list, vid) {
    if (Array.isArray(list) && list.length) {
      transcript = list.slice();
      currentLine = -1;
      paintTranscript(($("transcriptSearch") || {}).value || "");
      return;
    }
    if (!list && vid && typeof api !== "undefined") {
      api.get("/video/" + encodeURIComponent(vid) + "/transcript?page=1&page_size=500")
        .then(function (data) {
          transcript = (data && data.segments) || [];
          currentLine = -1;
          paintTranscript(($("transcriptSearch") || {}).value || "");
        })
        .catch(function () {
          transcript = [];
          paintTranscript("");
        });
      return;
    }
    transcript = [];
    paintTranscript("");
  };

  if (typeof document !== "undefined" && document.addEventListener && !window.__transcriptSearchBound) {
    window.__transcriptSearchBound = true;
    document.addEventListener("input", function (e) {
      if (e.target && e.target.id === "transcriptSearch") paintTranscript(e.target.value);
    });
  }

  /* copy the 60-second brief as markdown (feature: quick share/paste) */
  if (typeof document !== "undefined" && document.addEventListener && !window.__briefCopyBound) {
    window.__briefCopyBound = true;
    document.addEventListener("click", function (e) {
      var btn = e.target && e.target.closest ? e.target.closest("#briefCopy") : null;
      if (!btn) return;
      var v = (window.EDUCLIP && window.EDUCLIP.video) || {};
      var lines = [];
      if (v.title) lines.push("## " + v.title, "");
      (takeaways(v.summary) || []).forEach(function (s) { lines.push("- " + s); });
      var keys = ((v.keywords || []).map(function (k) { return k.term; }) || []).slice(0, 8);
      if (keys.length) {
        lines.push("", "**Key terms:** " + keys.join(", "), "");
      }
      var text = lines.join("\n");
      var done = function () {
        if (typeof showToast === "function") showToast("Brief copied as markdown.", "success");
        else btn.textContent = "Copied!";
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
      } else {
        fallbackCopy(text, done);
      }
    });
  }

  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (err) { /* unsupported */ }
    document.body.removeChild(ta);
  }

  function renderHeader(v) {
    var title = $("videoTitle");
    var meta = $("videoMeta");
    renderTopStrips(v);
    renderBrief(v);
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
    bindStudyButtons(data);
    if (typeof window.renderTranscript === "function") {
      window.renderTranscript(undefined, data.video_id);
    }
    if (data.flashcards === undefined && typeof window.renderFlashcards === "function") {
      // Payload had no cards — fall back to the dedicated endpoint.
      window.renderFlashcards(undefined, data.video_id);
    }
    if (typeof window.renderMCQs === "function") {
      // MCQs always come from the dedicated endpoint (keeps detail light).
      window.renderMCQs(undefined, data.video_id);
    }
  }

  function bindStudyButtons(data) {
    var resume = $("resumeBtn");
    if (resume) {
      var pos = readPos();
      var dur = Number(data.duration_sec) || 0;
      if (pos > 10 && (!dur || pos < dur - 10)) {
        resume.classList.remove("hidden");
        resume.textContent = "Resume at " + fmtStamp(pos);
        resume.onclick = function () { window.seekToTimestamp(pos); };
      } else resume.classList.add("hidden");
    }
    var cs = $("copySummary");
    if (cs && !cs._bound) {
      cs._bound = true;
      cs.addEventListener("click", function () {
        copyText((window.EDUCLIP && window.EDUCLIP.video && window.EDUCLIP.video.summary) || "", "Summary copied.");
      });
    }
    var ct = $("copyStamp");
    if (ct && !ct._bound) {
      ct._bound = true;
      ct.addEventListener("click", function () {
        var t = typeof window.getPlayerTime === "function" ? window.getPlayerTime() : 0;
        var url = window.location.origin + window.location.pathname + "#t=" + Math.floor(t);
        copyText(url, "Link copied (" + fmtStamp(t) + ").");
      });
    }
    if (!window.__posSaver) {
      window.__posSaver = true;
      window.addEventListener("pagehide", function () {
        try {
          if (playerReady && player && typeof player.getCurrentTime === "function") {
            savePos(player.getCurrentTime());
          }
        } catch (_) { /* noop */ }
      });
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
