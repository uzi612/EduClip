/* static/js/charts.js — Chart.js renderers (CHARTS-01: keyword density bar).
   Dark defaults, destroy-before-render, click-to-seek, a11y table fallback. */

(function () {
  "use strict";

  var VIOLET = "#8b5cf6";
  var CYAN = "#06b6d4";

  var live = {}; // canvas id -> Chart instance

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

  function applyDefaults() {
    if (typeof Chart === "undefined") return false;
    Chart.defaults.color = "#9ca3af";
    Chart.defaults.borderColor = "rgba(30,41,59,0.8)";
    Chart.defaults.font.family = "Inter";
    return true;
  }

  // Destroy-before-render: called directly and via store.setVideo().
  window.destroyCharts = function (ids) {
    var keys = ids || Object.keys(live);
    keys.forEach(function (id) {
      if (live[id] && typeof live[id].destroy === "function") live[id].destroy();
      delete live[id];
    });
  };

  function labelToSec(label) {
    var m = /^(\d+):([0-5]\d)$/.exec(String(label || "").trim());
    if (!m) return null;
    return Number(m[1]) * 60 + Number(m[2]);
  }

  function seekBucket(index, labels) {
    var sec = index * 60; // 60s buckets
    if (labels && labels[index] !== undefined) {
      var parsed = labelToSec(labels[index]);
      if (parsed !== null) sec = parsed;
    }
    if (typeof window.seekToTimestamp === "function") window.seekToTimestamp(sec);
  }

  // Lazy-init charts only when scrolled near (perf budget: no bundler in v1).
  function whenVisible(el, fn) {
    if (!el || typeof IntersectionObserver === "undefined") {
      fn();
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          io.disconnect();
          fn();
        }
      });
    }, { rootMargin: "200px" });
    io.observe(el);
  }

  function showState(which) {
    // which: "loading" | "pending" | "ready"
    var wrap = $("keywordChartWrap");
    var pending = $("keywordPending");
    if (which === "ready") {
      if (wrap) wrap.classList.remove("hidden");
      if (pending) pending.classList.add("hidden");
      return;
    }
    if (wrap) wrap.classList.add("hidden");
    if (pending) {
      pending.classList.remove("hidden");
      pending.innerHTML =
        which === "loading"
          ? '<div class="skel skel-chart"></div>'
          : '<div class="rounded-2xl border border-dashed border-slate-800 p-10 text-center">' +
            '<div class="text-3xl">📊</div>' +
            '<p class="mt-3 font-semibold">Analytics pending…</p>' +
            '<p class="mt-1 text-sm text-gray-400">Charts appear here once the video finishes processing.</p></div>';
    }
  }

  function renderTable(data) {
    var table = $("keywordTable");
    var details = $("keywordTableWrap");
    if (!table) return;
    var sets = data.datasets || [];
    var head =
      "<thead><tr><th class=\"text-left font-mono font-normal\">Bucket</th>" +
      sets.map(function (d) { return "<th class=\"text-right font-mono font-normal\">" + esc(d.label) + "</th>"; }).join("") +
      "</tr></thead>";
    var rows = (data.labels || [])
      .map(function (label, i) {
        var cells = sets
          .map(function (d) {
            return '<td class="text-right font-mono">' + esc((d.data || [])[i] !== undefined ? d.data[i] : "–") + "</td>";
          })
          .join("");
        return '<tr class="border-t border-slate-800"><td class="font-mono">' + esc(label) + "</td>" + cells + "</tr>";
      })
      .join("");
    table.innerHTML = head + "<tbody>" + rows + "</tbody>";
    if (details) details.classList.remove("hidden");
  }

  function renderKeywordChart(payload) {
    var canvas = $("keywordChart");
    if (!canvas || typeof Chart === "undefined") return false;
    applyDefaults();
    window.destroyCharts(["keywordChart"]);
    var data = payload.data || { labels: [], datasets: [] };
    var chart = new Chart(canvas, {
      type: payload.type || "bar",
      data: {
        labels: data.labels || [],
        datasets: (data.datasets || []).map(function (d, i) {
          var copy = {};
          for (var k in d) copy[k] = d[k];
          copy.backgroundColor = i === 0 ? VIOLET : CYAN;
          copy.borderRadius = 6;
          return copy;
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: function (evt, elements) {
          if (elements && elements.length) seekBucket(elements[0].index, data.labels);
        },
        onHover: function (evt, elements) {
          if (evt && evt.native && evt.native.target) {
            evt.native.target.style.cursor = elements && elements.length ? "pointer" : "default";
          }
        },
        plugins: {
          legend: { position: "bottom" },
          title: { display: true, text: "Keyword density / min" },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return " " + ctx.dataset.label + ": " + ctx.parsed.y + " hits";
              },
            },
          },
        },
        scales: {
          x: { title: { display: true, text: "Video time (60s buckets)" } },
          y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "Mentions" } },
        },
      },
    });
    live.keywordChart = chart;
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      "Bar chart of keyword mentions per minute: " +
        (data.datasets || []).map(function (d) { return d.label; }).join(", ")
    );
    renderTable(data);
    showState("ready");
    return true;
  }

  window.renderCharts = function (graphs, videoId) {
    var payload = graphs && graphs.keyword_density;
    if (payload && payload.data) {
      whenVisible($("keywordChartWrap") || $("keywordChart"), function () {
        if (!renderKeywordChart(payload)) showState("pending");
      });
      return;
    }
    if (!videoId || typeof api === "undefined") {
      showState("pending");
      return;
    }
    // Payload had no graphs — try the dedicated endpoint (backend order may vary).
    showState("loading");
    api
      .get("/video/" + encodeURIComponent(videoId) + "/analytics")
      .then(function (data) {
        var g = (data && data.graphs) || data;
        if (g && g.keyword_density && g.keyword_density.data) {
          whenVisible($("keywordChartWrap") || $("keywordChart"), function () {
            if (!renderKeywordChart(g.keyword_density)) showState("pending");
          });
        } else {
          showState("pending");
        }
      })
      .catch(function () {
        showState("pending");
      });
  };
})();
