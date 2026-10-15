/* static/js/mcq.js — practice quiz: render, instant validation, scoring.
   Questions come from GET /video/<id>/mcqs (see apps/quiz/models.py).
   Depends on static/js/api.js (api, showToast). No other dependencies. */

(function () {
  "use strict";

  var questions = [];
  var answers = {}; // index -> chosen option

  var LETTERS = ["A", "B", "C", "D"];

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

  function score() {
    var got = 0;
    var done = 0;
    for (var i = 0; i < questions.length; i++) {
      if (answers[i] === undefined || answers[i] === null) continue;
      done++;
      if (answers[i] === questions[i].answer_index) got++;
    }
    return { got: got, done: done, total: questions.length };
  }

  function paintScore() {
    var counter = $("mcqCounter");
    var badge = $("mcqScore");
    var s = score();
    if (counter) counter.textContent = questions.length ? s.done + " / " + s.total + " answered" : "";
    if (badge) {
      if (!questions.length) {
        badge.classList.add("hidden");
        return;
      }
      badge.classList.remove("hidden");
      badge.textContent = "Score " + s.got + " / " + s.total;
    }
  }

  function optionHTML(q, qi, text, oi) {
    var picked = answers[qi];
    var locked = picked !== undefined && picked !== null;
    var cls = "border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-900/50 hover:border-violet-500/50";
    var mark = "";
    if (locked) {
      if (oi === q.answer_index) {
        cls = "border-emerald-500/60 bg-emerald-500/10";
        mark = '<span class="ml-auto font-bold text-emerald-700 dark:text-emerald-300" aria-hidden="true">✓</span>';
      } else if (oi === picked) {
        cls = "border-red-500/60 bg-red-500/10";
        mark = '<span class="ml-auto font-bold text-red-700 dark:text-red-300" aria-hidden="true">✗</span>';
      } else {
        cls = "border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-900/50 opacity-60";
      }
    }
    return (
      '<button type="button" data-mcq="' + qi + '" data-opt="' + oi + '"' +
      (locked ? " disabled aria-disabled=\"true\"" : "") +
      ' class="w-full flex items-center gap-3 text-left px-4 py-3 rounded-xl border text-sm text-slate-800 dark:text-gray-200 transition ' + cls + '">' +
      '<span class="grid place-items-center w-6 h-6 rounded-md bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-gray-300 text-xs font-mono shrink-0" aria-hidden="true">' +
      LETTERS[oi] + "</span>" +
      "<span>" + esc(text) + "</span>" + mark +
      "</button>"
    );
  }

  function questionHTML(q, qi) {
    var picked = answers[qi];
    var locked = picked !== undefined && picked !== null;
    var correct = locked && picked === q.answer_index;
    return (
      '<div class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-4 sm:p-5" data-mcq-card="' + qi + '">' +
      '<div class="flex items-start justify-between gap-2">' +
      '<p class="font-semibold text-slate-900 dark:text-gray-100">' + esc(q.question) + "</p>" +
      '<button type="button" data-seek="' + esc(q.timestamp_sec || 0) + '" title="Jump to ' +
      esc(fmtStamp(q.timestamp_sec)) + ' in the video"' +
      ' class="shrink-0 px-2 py-1 rounded-lg font-mono text-xs text-cyan-700 dark:text-cyan-300 border border-cyan-500/30 bg-cyan-500/10 hover:border-cyan-400/60 transition">' +
      esc(fmtStamp(q.timestamp_sec)) + "</button></div>" +
      '<div class="mt-3 grid gap-2" role="group" aria-label="Question ' + (qi + 1) + " of " + questions.length + '">' +
      q.options.map(function (text, oi) {
        return optionHTML(q, qi, text, oi);
      }).join("") +
      "</div>" +
      (locked
        ? '<div class="mt-3 rounded-xl px-4 py-3 text-sm ' +
          (correct
            ? "border border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
            : "border border-red-500/40 bg-red-500/10 text-red-800 dark:text-red-200") +
          '" role="status">' +
          "<strong>" + (correct ? "Correct. " : "Not quite. ") + "</strong>" +
          esc(q.explanation || "") + "</div>"
        : "") +
      "</div>"
    );
  }

  var degradedMode = false;

  function render() {
    var list = $("mcqList");
    var empty = $("mcqEmpty");
    if (!list) return;
    paintScore();
    if (!questions.length) {
      list.innerHTML = "";
      if (empty) {
        empty.classList.remove("hidden");
        if (degradedMode) {
          empty.innerHTML =
            '<p class="mt-3 font-semibold text-slate-900 dark:text-gray-100">No quiz for fallback analysis</p>' +
            '<p class="mt-1 text-sm text-slate-500 dark:text-gray-400">This video used rule-based fallback ' +
            "instead of AI analysis, so there are no real questions to ask yet. " +
            "Re-process with an LLM key configured for the full quiz.</p>";
        }
      }
      return;
    }
    if (empty) empty.classList.add("hidden");
    list.innerHTML = questions.map(questionHTML).join("");
  }

  window.renderMCQs = function (list, videoId) {
    if (Array.isArray(list) && list.length) {
      questions = list.slice();
      answers = {};
      degradedMode = false;
      render();
      return;
    }
    if (!list && videoId && typeof api !== "undefined") {
      api
        .get("/video/" + encodeURIComponent(videoId) + "/mcqs")
        .then(function (data) {
          questions = (data && data.mcqs) || [];
          answers = {};
          degradedMode = Boolean(data && data.degraded) && !questions.length;
          render();
        })
        .catch(function () {
          questions = [];
          answers = {};
          degradedMode = false;
          render();
        });
      return;
    }
    questions = [];
    answers = {};
    degradedMode = false;
    render();
  };

  document.addEventListener("click", function (e) {
    var opt = e.target.closest ? e.target.closest("[data-mcq]") : null;
    if (opt && opt.hasAttribute("data-opt")) {
      var qi = Number(opt.getAttribute("data-mcq"));
      var oi = Number(opt.getAttribute("data-opt"));
      if (answers[qi] !== undefined && answers[qi] !== null) return; // locked
      answers[qi] = oi;
      render();
      var card = document.querySelector('[data-mcq-card="' + qi + '"]');
      if (card) {
        var next = card.nextElementSibling;
        if (next && next.scrollIntoView) {
          next.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
      return;
    }
    if (e.target.closest && e.target.closest("#mcqRestart")) {
      answers = {};
      render();
      if (typeof showToast === "function") showToast("Quiz restarted.", "info");
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    if ($("mcqList")) render();
  });
})();
