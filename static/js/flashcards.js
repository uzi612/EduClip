/* static/js/flashcards.js — 3D flip deck: render, flip, shuffle, prev/next, keyboard.
   Relies on the single delegated [data-seek] listener in player.js for jumps. */

(function () {
  "use strict";

  var cards = [];
  var current = -1;

  var DIFF_STYLE = {
    easy: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    hard: "bg-red-500/15 text-red-300 border-red-500/30",
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

  function fmtStamp(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function scenes() {
    return Array.prototype.slice.call(document.querySelectorAll("#flashDeck .flash-scene"));
  }

  function paintCounter() {
    var el = $("flashCounter");
    if (!el) return;
    el.textContent = cards.length ? current + 1 + " / " + cards.length : "";
  }

  function highlight() {
    var list = scenes();
    for (var i = 0; i < list.length; i++) {
      var on = i === current;
      list[i].classList.toggle("ring-2", on);
      list[i].classList.toggle("ring-cyan-400", on);
    }
    paintCounter();
  }

  function focusCurrent(scroll) {
    var list = scenes();
    if (current < 0 || current >= list.length) return;
    list[current].focus({ preventScroll: !scroll });
    if (scroll && typeof list[current].scrollIntoView === "function") {
      list[current].scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function cardHTML(c) {
    var diff = DIFF_STYLE[c.difficulty] || DIFF_STYLE.medium;
    var tagBits = [fmtStamp(c.timestamp_sec)]
      .concat(c.tags || [])
      .map(esc)
      .join(" · ");
    return (
      '<div class="flash-scene rounded-2xl" tabindex="0" role="button" aria-label="Flashcard: ' +
      esc(c.front || "Untitled") +
      '. Activate to flip.">' +
      '<div class="flash-inner">' +
      '<div class="flash-face flash-front">' +
      '<div class="flex items-center justify-between gap-2">' +
      '<span class="text-xs font-mono text-cyan-400">' + tagBits + "</span>" +
      '<span class="px-2 py-0.5 rounded-full border text-[11px] font-mono ' + diff + '">' +
      esc(c.difficulty || "medium") +
      "</span></div>" +
      '<p class="mt-2 font-semibold">' + esc(c.front || "Untitled") + "</p>" +
      '<span class="mt-4 text-xs text-gray-400">Click to reveal →</span>' +
      "</div>" +
      '<div class="flash-face flash-back">' +
      '<p class="text-sm leading-relaxed">' + esc(c.back || "") + "</p>" +
      '<button type="button" data-seek="' + esc(c.timestamp_sec || 0) + '" class="mt-4 text-xs underline underline-offset-2 self-start hover:opacity-80 transition">↗ Jump to ' +
      esc(fmtStamp(c.timestamp_sec)) +
      "</button>" +
      "</div></div></div>"
    );
  }

  function skeletonHTML() {
    var out = "";
    for (var i = 0; i < 6; i++) {
      out += '<div class="skel skel-flash"></div>';
    }
    return out;
  }

  function render() {
    var deck = $("flashDeck");
    var empty = $("flashEmpty");
    if (!deck) return;
    if (!cards.length) {
      deck.innerHTML = "";
      if (empty) empty.classList.remove("hidden");
      current = -1;
      paintCounter();
      return;
    }
    if (empty) empty.classList.add("hidden");
    deck.innerHTML = cards.map(cardHTML).join("");
    if (current < 0 || current >= cards.length) current = 0;
    highlight();
  }

  window.renderFlashcards = function (list, videoId) {
    if (Array.isArray(list) && list.length) {
      cards = list.slice();
      current = 0;
      render();
      return;
    }
    if (!list && videoId) {
      // Payload had no cards — try the dedicated endpoint (backend order may vary).
      api
        .get("/video/" + encodeURIComponent(videoId) + "/flashcards?page=1&page_size=50")
        .then(function (data) {
          cards = (data && data.flashcards) || [];
          current = 0;
          render();
        })
        .catch(function () {
          cards = [];
          render();
        });
      return;
    }
    cards = [];
    render();
  };

  function shuffle() {
    for (var i = cards.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = cards[i];
      cards[i] = cards[j];
      cards[j] = tmp;
    }
    current = 0;
    render();
    focusCurrent(true);
    if (typeof showToast === "function") showToast("Deck shuffled.", "info");
  }

  function step(d) {
    if (!cards.length) return;
    current = (current + d + cards.length) % cards.length;
    highlight();
    focusCurrent(true);
  }

  // Flip on click (except jump links — the [data-seek] listener owns those).
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-seek]")) return;
    var scene = e.target.closest("#flashDeck .flash-scene");
    if (scene) scene.classList.toggle("flipped");
  });

  // Keyboard: Enter/Space flips; arrows move through the deck.
  document.addEventListener("keydown", function (e) {
    var scene = e.target.closest ? e.target.closest("#flashDeck .flash-scene") : null;
    if ((e.key === "Enter" || e.key === " ") && scene) {
      if (e.target.closest("[data-seek]")) return;
      e.preventDefault();
      scene.classList.toggle("flipped");
      return;
    }
    if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && scene) {
      e.preventDefault();
      step(e.key === "ArrowRight" ? 1 : -1);
    }
  });

  function boot() {
    var deck = $("flashDeck");
    if (!deck) return; // not the watch page
    deck.innerHTML = skeletonHTML();
    var prev = $("flashPrev");
    var next = $("flashNext");
    var sh = $("flashShuffle");
    if (prev) prev.addEventListener("click", function () { step(-1); });
    if (next) next.addEventListener("click", function () { step(1); });
    if (sh) sh.addEventListener("click", shuffle);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
