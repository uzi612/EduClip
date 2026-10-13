/* static/js/notes.js — timestamped scratchpad (localStorage) + study-pack export.
   Depends on static/js/api.js (showToast) and player.js (window.getPlayerTime). */

(function () {
  "use strict";

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

  function studyMarkdown() {
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
    var md = $("exportMd");
    if (md) {
      md.addEventListener("click", function () {
        var v = currentVideo() || {};
        var slug = String(v.title || "educlip-notes").toLowerCase()
          .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "educlip-notes";
        download(slug + ".md", studyMarkdown(), "text/markdown;charset=utf-8");
        if (typeof showToast === "function") showToast("Study pack downloaded.", "success");
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
