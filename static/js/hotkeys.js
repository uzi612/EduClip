/* static/js/hotkeys.js — "?" shortcut overlay listing every keyboard shortcut.
   Standalone: focus close button on open, Esc/backdrop close, focus restore. */

(function () {
  "use strict";

  var overlay = null;
  var lastFocus = null;

  var SHORTCUTS = [
    ["Enter / Space", "Flip the focused flashcard"],
    ["← / →", "Previous / next card (skip in quiz, ±10s on the timeline)"],
    ["Tab", "Move through cards, chapters, and controls"],
    ["Esc", "Close dialogs"],
    ["?", "Open this cheat sheet"],
  ];

  function close() {
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    overlay = null;
    document.removeEventListener("keydown", onKey, true);
    if (lastFocus && typeof lastFocus.focus === "function") {
      try {
        lastFocus.focus();
      } catch (_) {
        /* noop */
      }
    }
  }

  function onKey(e) {
    if (!overlay) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  }

  function open() {
    if (overlay) return;
    lastFocus = document.activeElement;
    overlay = document.createElement("div");
    overlay.className = "fixed inset-0 z-50 flex items-center justify-center p-4";
    var rows = SHORTCUTS.map(function (s) {
      return (
        '<div class="flex items-center justify-between gap-6 py-2 border-b border-slate-800/70">' +
        '<span class="font-mono text-xs text-cyan-300">' + s[0] + "</span>" +
        '<span class="text-sm text-gray-300 text-right">' + s[1] + "</span></div>"
      );
    }).join("");
    overlay.innerHTML =
      '<div class="absolute inset-0 bg-black/70 backdrop-blur-sm" data-hotkeys-close></div>' +
      '<div role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" ' +
      'class="relative w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">' +
      '<h2 class="text-lg font-bold tracking-tight">Keyboard shortcuts</h2>' +
      '<div class="mt-4">' + rows + "</div>" +
      '<div class="mt-6 flex justify-end">' +
      '<button type="button" data-hotkeys-close class="px-4 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-cyan-500 hover:opacity-90 transition">Done</button>' +
      "</div></div>";
    overlay.addEventListener("click", function (e) {
      if (e.target.closest("[data-hotkeys-close]")) close();
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    var btn = overlay.querySelector("[data-hotkeys-close]");
    if (btn) btn.focus();
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "?") return;
    var tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
    e.preventDefault();
    if (overlay) close();
    else open();
  });

  window.closeHotkeys = close;
})();
