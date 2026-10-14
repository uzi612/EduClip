/* static/js/notes.js — timestamped scratchpad (localStorage) + study-pack export.
   Depends on static/js/api.js (showToast) and player.js (window.getPlayerTime). */

(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function fmtStamp(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function videoIdFromPath() {
    var m = window.location.pathname.match(/^\/watch\/([^/]+)\/?$/);
    return m ? decodeURIComponent(m[1]) : "home";
  }

  function storeKey() {
    return "educlip-scratch-" + videoIdFromPath();
  }

  function currentVideo() {
    return (window.EDUCLIP && window.EDUCLIP.video) || null;
  }

  /* ---------- scratchpad ---------- */

  var saveTimer = null;

  function markSaved() {
    var el = $("scratchSaved");
    if (!el) return;
    var now = new Date();
    var hh = String(now.getHours()).padStart(2, "0");
    var mm = String(now.getMinutes()).padStart(2, "0");
    var ss = String(now.getSeconds()).padStart(2, "0");
    el.textContent = "Saved " + hh + ":" + mm + ":" + ss + " in this browser.";
  }

  function saveNow() {
    var box = $("scratchText");
    if (!box) return;
    try {
      localStorage.setItem(storeKey(), box.value);
    } catch (_) {
      /* private mode: keep it session-only */
    }
    markSaved();
  }

  function insertTimestamp() {
    var box = $("scratchText");
    if (!box) return;
    var t = typeof window.getPlayerTime === "function" ? window.getPlayerTime() : 0;
    var tag = "[" + fmtStamp(t) + "] ";
    var start = box.selectionStart == null ? box.value.length : box.selectionStart;
    var end = box.selectionEnd == null ? start : box.selectionEnd;
    box.value = box.value.slice(0, start) + tag + box.value.slice(end);
    var caret = start + tag.length;
    try {
      box.focus();
      box.setSelectionRange(caret, caret);
    } catch (_) {
      /* older browsers */
    }
    saveNow();
  }

  /* ---------- export ---------- */

  function download(filename, text, mime) {
    var blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 500);
  }

  function studyMarkdown(mcqs) {
    var v = currentVideo() || {};
    var lines = ["# " + (v.title || "Untitled video"), ""];
    if (v.channel) lines.push("*" + v.channel + "*");
    lines.push("");
    if (v.summary) {
      lines.push("## Summary", "", v.summary, "");
    }
    var chapters = v.chapters || [];
    if (chapters.length) {
      lines.push("## Chapters", "");
      chapters.forEach(function (c) {
        lines.push("### " + (c.title || "Untitled") + " (" + fmtStamp(c.start_sec) + " → " + fmtStamp(c.end_sec) + ")");
        if (c.summary) lines.push("", c.summary);
        lines.push("");
      });
    }
    var cards = (window.EDUCLIP && window.EDUCLIP.flashcards) || v.flashcards || [];
    if (cards.length) {
      lines.push("## Flashcards", "");
      cards.forEach(function (c, i) {
        lines.push((i + 1) + ". **Q:** " + (c.front || ""));
        lines.push("   **A:** " + (c.back || ""));
        lines.push("");
      });
    }
    var kws = v.keywords || [];
    if (kws.length) {
      lines.push("## Keywords", "",
        kws.map(function (k) { return "- " + k.term + " (×" + k.count + ")"; }).join("\n"), "");
    }
    mcqs = mcqs || [];
    if (mcqs.length) {
      lines.push("## Practice quiz", "");
      mcqs.forEach(function (q, i) {
        lines.push((i + 1) + ". " + (q.question || ""));
        (q.options || []).forEach(function (o, oi) {
          lines.push("   " + String.fromCharCode(65 + oi) + ") " + o +
            (oi === q.answer_index ? " ✓" : ""));
        });
        if (q.explanation) lines.push("   _" + q.explanation + "_");
        lines.push("");
      });
    }
    var box = $("scratchText");
    if (box && box.value.trim()) {
      lines.push("## My notes", "", box.value.trim(), "");
    }
    lines.push("---", "_Exported from EduClip AI_");
    return lines.join("\n");
  }

  function boot() {
    var box = $("scratchText");
    if (!box) return; // not the watch page
    try {
      box.value = localStorage.getItem(storeKey()) || "";
    } catch (_) {
      /* private mode */
    }
    if (box.value) markSaved();
    box.addEventListener("input", function () {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveNow, 500);
    });
    var stamp = $("scratchStamp");
    if (stamp) stamp.addEventListener("click", insertTimestamp);
    // Unified export modal (Markdown / plain text / print-to-PDF).
    var overlay = null;
    var lastFocus = null;

    function slugFor(v) {
      return String((v && v.title) || "educlip-notes").toLowerCase()
        .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "educlip-notes";
    }

    function closeExport() {
      if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
      overlay = null;
      document.removeEventListener("keydown", onExportKey, true);
      if (lastFocus && typeof lastFocus.focus === "function") {
        try {
          lastFocus.focus();
        } catch (_) {
          /* noop */
        }
      }
    }

    function onExportKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        closeExport();
      }
    }

    function withMcqs(v, done) {
      if (v.video_id && typeof api !== "undefined") {
        api.get("/video/" + encodeURIComponent(v.video_id) + "/mcqs")
          .then(function (data) { done((data && data.mcqs) || []); })
          .catch(function () { done([]); });
      } else {
        done([]);
      }
    }

    function openExport() {
      var v = currentVideo() || {};
      if (v.status && v.status !== "ready") {
        if (typeof showToast === "function") {
          showToast("Not ready yet — export unlocks once processing finishes.", "info");
        }
        return;
      }
      closeExport();
      lastFocus = document.activeElement;
      overlay = document.createElement("div");
      overlay.className = "fixed inset-0 z-50 flex items-center justify-center p-4";
      overlay.innerHTML =
        '<div class="absolute inset-0 bg-black/70 backdrop-blur-sm" data-export-close></div>' +
        '<div role="dialog" aria-modal="true" aria-label="Export study pack" ' +
        'class="relative w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">' +
        '<h2 class="text-lg font-bold tracking-tight">Export study pack</h2>' +
        '<p class="mt-1 text-sm text-gray-400">Summary, chapters, flashcards, quiz, and notes.</p>' +
        '<div class="mt-5 grid gap-2">' +
        '<button type="button" data-export="md" class="w-full text-left px-4 py-3 rounded-xl border border-slate-800 bg-slate-900/50 hover:border-violet-500/50 transition"><span class="font-semibold">Markdown</span><span class="block text-xs text-gray-400">Structured .md file for notes apps</span></button>' +
        '<button type="button" data-export="txt" class="w-full text-left px-4 py-3 rounded-xl border border-slate-800 bg-slate-900/50 hover:border-violet-500/50 transition"><span class="font-semibold">Plain text</span><span class="block text-xs text-gray-400">Simple .txt file, no formatting</span></button>' +
        '<button type="button" data-export="print" class="w-full text-left px-4 py-3 rounded-xl border border-slate-800 bg-slate-900/50 hover:border-violet-500/50 transition"><span class="font-semibold">Print / PDF</span><span class="block text-xs text-gray-400">Print dialog, styled for paper</span></button>' +
        "</div>" +
        '<div class="mt-5 flex justify-end">' +
        '<button type="button" data-export-close class="px-4 py-2 rounded-xl text-sm border border-slate-800 text-gray-300 hover:text-white transition">Cancel</button>' +
        "</div></div>";
      overlay.addEventListener("click", function (e) {
        if (e.target.closest("[data-export-close]")) {
          closeExport();
          return;
        }
        var btn = e.target.closest("[data-export]");
        if (!btn) return;
        var kind = btn.getAttribute("data-export");
        if (kind === "print") {
          closeExport();
          window.print();
          return;
        }
        withMcqs(v, function (mcqs) {
          if (kind === "txt") {
            var plain = studyMarkdown(mcqs)
              .replace(/^#{1,3} /gm, "")
              .replace(/\*\*/g, "")
              .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
            download(slugFor(v) + ".txt", plain, "text/plain;charset=utf-8");
          } else {
            download(slugFor(v) + ".md", studyMarkdown(mcqs), "text/markdown;charset=utf-8");
          }
          if (typeof showToast === "function") showToast("Study pack downloaded.", "success");
        });
        closeExport();
      });
      document.addEventListener("keydown", onExportKey, true);
      document.body.appendChild(overlay);
      var first = overlay.querySelector("[data-export]");
      if (first) first.focus();
    }

    var opener = $("exportOpen");
    if (opener) opener.addEventListener("click", openExport);
    // Legacy direct buttons (kept working if present in older markup).
    var md = $("exportMd");
    if (md) {
      md.addEventListener("click", function () {
        var v = currentVideo() || {};
        if (v.status && v.status !== "ready") {
          if (typeof showToast === "function") {
            showToast("Not ready yet — export unlocks once processing finishes.", "info");
          }
          return;
        }
        withMcqs(v, function (mcqs) {
          download(slugFor(v) + ".md", studyMarkdown(mcqs), "text/markdown;charset=utf-8");
          if (typeof showToast === "function") showToast("Study pack downloaded.", "success");
        });
      });
    }
    var print = $("exportPrint");
    if (print) print.addEventListener("click", function () { window.print(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
