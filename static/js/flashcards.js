/* static/js/flashcards.js — 3D flip deck: render, flip, shuffle, prev/next, keyboard.
   Relies on the single delegated [data-seek] listener in player.js for jumps. */

(function () {
  "use strict";

  var cards = [];
  var current = -1;
  var filter = "all";
  var quiz = null; // {order: [visibleIdx...], pos: number, got: number, missed: number}
  var RTF = typeof richText === "function" ? richText : esc;

  function visibleCards() {
    if (filter === "all") return cards.slice();
    return cards.filter(function (c) {
      return (c.difficulty || "medium") === filter;
    });
  }

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
      '<div class="text-sm leading-relaxed rich-text">' + RTF(c.back || "") + "</div>" +
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

  function paintQuizBar() {
    var bar = $("quizBar");
    var score = $("quizScore");
    if (!bar) return;
    if (!quiz) {
      bar.classList.add("hidden");
      return;
    }
    bar.classList.remove("hidden");
    var total = quiz.order.length;
    if (score) score.textContent = quiz.got + " correct · " + quiz.missed + " missed · Q " +
      Math.min(quiz.pos + 1, total) + " / " + total;
    var counter = $("flashCounter");
    if (counter) counter.textContent = "Quiz " + Math.min(quiz.pos + 1, total) + " / " + total;
  }

  function renderFilters() {
    var wrap = $("diffFilters");
    if (!wrap) return;
    var levels = ["all", "easy", "medium", "hard"];
    wrap.innerHTML = levels
      .map(function (lv) {
        var on = lv === filter;
        return (
          '<button type="button" data-diff="' + lv + '" aria-pressed="' + on + '"' +
          ' class="px-3 py-1.5 rounded-full text-xs font-mono border transition ' +
          (on
            ? "border-violet-500/60 bg-violet-500/15 text-violet-200"
            : "border-slate-800 bg-slate-900/50 text-gray-400 hover:text-gray-100") +
          '">' + lv + "</button>"
        );
      })
      .join("");
  }

  function quizCard() {
    var vis = visibleCards();
    if (!quiz || quiz.pos >= quiz.order.length) return null;
    return vis[quiz.order[quiz.pos]] || null;
  }

  function enterQuiz() {
    var vis = visibleCards();
    if (!vis.length) return;
    var order = vis.map(function (_, i) {
      return i;
    });
    for (var i = order.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = order[i];
      order[i] = order[j];
      order[j] = tmp;
    }
    quiz = { order: order, pos: 0, got: 0, missed: 0 };
    var mode = $("deckMode");
    if (mode) {
      mode.textContent = "Exit quiz";
      mode.setAttribute("aria-pressed", "true");
    }
    render();
  }

  function exitQuiz() {
    quiz = null;
    var mode = $("deckMode");
    if (mode) {
      mode.textContent = "Quiz mode";
      mode.setAttribute("aria-pressed", "false");
    }
    render();
  }

  function answerQuiz(ok) {
    if (!quiz) return;
    if (ok) quiz.got++;
    else quiz.missed++;
    quiz.pos++;
    if (quiz.pos >= quiz.order.length) {
      paintQuizBar();
      if (typeof showToast === "function") {
        showToast("Quiz done: " + quiz.got + " correct, " + quiz.missed + " missed.", "success");
      }
      exitQuiz();
      return;
    }
    render();
  }

  function render() {
    var deck = $("flashDeck");
    var empty = $("flashEmpty");
    if (!deck) return;
    renderFilters();
    var vis = visibleCards();
    if (quiz) {
      var card = quizCard();
      if (empty) empty.classList.add("hidden");
      deck.innerHTML = card ? cardHTML(card) : "";
      current = 0;
      paintQuizBar();
      return;
    }
    paintQuizBar();
    if (!vis.length) {
      deck.innerHTML = "";
      if (empty) empty.classList.remove("hidden");
      current = -1;
      paintCounter();
      return;
    }
    if (empty) empty.classList.add("hidden");
    deck.innerHTML = vis.map(cardHTML).join("");
    if (current < 0 || current >= vis.length) current = 0;
    highlight();
  }

  window.renderFlashcards = function (list, videoId) {
    if (Array.isArray(list) && list.length) {
      cards = list.slice();
      window.EDUCLIP = window.EDUCLIP || {};
      window.EDUCLIP.flashcards = cards.slice(); // shared read-only for export
      current = 0;
      quiz = null;
      var mode = $("deckMode");
      if (mode) {
        mode.textContent = "Quiz mode";
        mode.setAttribute("aria-pressed", "false");
      }
      render();
      return;
    }
    if (!list && videoId) {
      // Payload had no cards — try the dedicated endpoint (backend order may vary).
      api
        .get("/video/" + encodeURIComponent(videoId) + "/flashcards?page=1&page_size=50")
        .then(function (data) {
          cards = (data && data.flashcards) || [];
          window.EDUCLIP = window.EDUCLIP || {};
          window.EDUCLIP.flashcards = cards.slice();
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
    if (quiz) {
      enterQuiz(); // re-deal the quiz order
      return;
    }
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
    if (quiz) {
      // Arrow keys skip without scoring in quiz mode.
      quiz.pos = (quiz.pos + d + quiz.order.length) % quiz.order.length;
      render();
      focusCurrent(true);
      return;
    }
    var vis = visibleCards();
    if (!vis.length) return;
    current = (current + d + vis.length) % vis.length;
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
    var mode = $("deckMode");
    if (mode) mode.addEventListener("click", function () {
      if (quiz) exitQuiz();
      else enterQuiz();
    });
    var got = $("quizGot");
    var missed = $("quizMissed");
    var restart = $("quizRestart");
    if (got) got.addEventListener("click", function () { answerQuiz(true); });
    if (missed) missed.addEventListener("click", function () { answerQuiz(false); });
    if (restart) restart.addEventListener("click", function () { enterQuiz(); });
    renderFilters();
  }

  document.addEventListener("click", function (e) {
    var chip = e.target.closest("[data-diff]");
    if (!chip) return;
    filter = chip.getAttribute("data-diff") || "all";
    current = 0;
    if (quiz) {
      var mode = $("deckMode");
      quiz = null;
      if (mode) {
        mode.textContent = "Quiz mode";
        mode.setAttribute("aria-pressed", "false");
      }
    }
    render();
    focusCurrent(false);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
