/* static/js/modal.js — accessible alert modal: focus trap, Esc/backdrop close,
   Retry action, focus restore. Used for terminal submit failures. */

(function () {
  "use strict";

  var overlay = null;
  var lastFocus = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function focusables() {
    if (!overlay) return [];
    return Array.prototype.slice.call(
      overlay.querySelectorAll('button, [href], [tabindex]:not([tabindex="-1"])')
    );
  }

  function onKey(e) {
    if (!overlay) return;
    if (e.key === "Escape") {
      e.preventDefault();
      closeModal();
      return;
    }
    if (e.key !== "Tab") return;
    var items = focusables();
    if (!items.length) {
      e.preventDefault();
      return;
    }
    var first = items[0];
    var last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function closeModal() {
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

  window.showModal = function (opts) {
    opts = opts || {};
    closeModal();
    lastFocus = document.activeElement;

    overlay = document.createElement("div");
    overlay.className = "fixed inset-0 z-50 flex items-center justify-center p-4";
    overlay.innerHTML =
      '<div class="absolute inset-0 bg-black/70 backdrop-blur-sm" data-modal-close></div>' +
      '<div role="alertdialog" aria-modal="true" aria-labelledby="modalTitle" aria-describedby="modalMsg" class="relative w-full max-w-md rounded-2xl border border-slate-800 bg-panel p-6 shadow-2xl">' +
      '<h2 id="modalTitle" class="text-lg font-bold tracking-tight">' + esc(opts.title || "Something went wrong") + "</h2>" +
      '<p id="modalMsg" class="mt-2 text-sm text-gray-400">' + esc(opts.message || "") + "</p>" +
      '<div class="mt-6 flex justify-end gap-2">' +
      '<button type="button" data-modal-close class="px-4 py-2 rounded-xl text-sm border border-slate-800 bg-slate-900/70 text-gray-300 hover:text-gray-100 transition">' +
      esc(opts.dismissLabel || "Dismiss") +
      "</button>" +
      '<button type="button" data-modal-retry class="px-4 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-cyan-500 hover:opacity-90 transition">' +
      esc(opts.retryLabel || "Retry") +
      "</button></div></div>";

    overlay.addEventListener("click", function (e) {
      if (e.target.closest("[data-modal-close]")) {
        closeModal();
        return;
      }
      if (e.target.closest("[data-modal-retry]")) {
        var fn = opts.onRetry;
        closeModal();
        if (typeof fn === "function") fn();
      }
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);

    var items = focusables();
    var retry = overlay.querySelector("[data-modal-retry]");
    (retry || items[0] || overlay).focus();
  };

  window.closeModal = closeModal;
})();
