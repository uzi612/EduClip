/* static/js/charts.js — Chart.js renderers (CHARTS-01: keyword density bar).
   Dark defaults, destroy-before-render, click-to-seek, a11y table fallback. */

(function () {
  "use strict";

  var VIOLET = "#8b5cf6";
  var CYAN = "#06b6d4";
  var EMERALD = "#10b981";
  var AMBER = "#f59e0b";
  var RED = "#ef4444";
  var TOPIC_COLORS = [VIOLET, CYAN, EMERALD, AMBER, RED];

  var live = {}; // canvas id -> Chart instance
  var topicCtx = { values: [], labels: [] };

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

  function fmtDur(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function getChapters() {
    return (window.EDUCLIP && window.EDUCLIP.chapters) || [];
  }

  // Highlight the matching chapter sidebar row (best-effort cross-link).
  function highlightChapterRow(index, on) {
    if (typeof document === "undefined" || !document.querySelectorAll) return;
    var rows = document.querySelectorAll(".chapter-row");
    if (rows && rows[index] && rows[index].classList) {
      rows[index].classList.toggle("border-cyan-400/60", on);
    }
  }
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

  function pendingCopy() {
    return (
      '<div class="rounded-2xl border border-dashed border-slate-800 p-10 text-center">' +
      '<div class="text-3xl">📊</div>' +
      '<p class="mt-3 font-semibold">Analytics pending…</p>' +
      '<p class="mt-1 text-sm text-gray-400">Charts appear here once the video finishes processing.</p></div>'
    );
  }

  // Per-card states ("keyword" | "topic"); which: "loading" | "pending" | "ready".
  function showCardState(prefix, which) {
    var wrap = $(prefix + "ChartWrap");
    var pending = $(prefix + "Pending");
    if (which === "ready") {
      if (wrap) wrap.classList.remove("hidden");
      if (pending) pending.classList.add("hidden");
      return;
    }
    if (wrap) wrap.classList.add("hidden");
    if (pending) {
      pending.classList.remove("hidden");
      pending.innerHTML = which === "loading" ? '<div class="skel skel-chart"></div>' : pendingCopy();
    }
  }

  function showState(which) {
    showCardState("keyword", which);
  }

  // Generic a11y data table: headLabels + rows of cell strings.
  function renderTableInto(tableId, detailsId, headLabels, rowArrays) {
    var table = $(tableId);
    var details = $(detailsId);
    if (!table) return;
    var head =
      "<thead><tr>" +
      headLabels
        .map(function (h, i) {
          return '<th class="' + (i === 0 ? "text-left" : "text-right") + ' font-mono font-normal">' + esc(h) + "</th>";
        })
        .join("") +
      "</tr></thead>";
    var rows = rowArrays
      .map(function (cells) {
        return (
          '<tr class="border-t border-slate-800">' +
          cells
            .map(function (c, i) {
              return '<td class="' + (i === 0 ? "font-mono" : "text-right font-mono") + '">' + esc(c) + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    table.innerHTML = head + "<tbody>" + rows + "</tbody>";
    if (details) details.classList.remove("hidden");
  }

  function renderTable(data) {
    var sets = data.datasets || [];
    renderTableInto(
      "keywordTable",
      "keywordTableWrap",
      ["Bucket"].concat(
        sets.map(function (d) {
          return d.label;
        })
      ),
      (data.labels || []).map(function (label, i) {
        return [label].concat(
          sets.map(function (d) {
            return (d.data || [])[i] !== undefined ? String(d.data[i]) : "–";
          })
        );
      })
    );
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

  // Segment i starts at the cumulative duration of earlier segments.
  function segmentStart(values, i) {
    var s = 0;
    for (var j = 0; j < i && j < values.length; j++) s += values[j];
    return Math.floor(s);
  }

  function seekSegment(i) {
    if (typeof window.seekToTimestamp === "function") {
      window.seekToTimestamp(segmentStart(topicCtx.values, i));
    }
  }

  function renderLegend(labels, pcts, colors) {
    var box = $("topicLegend");
    if (!box) return;
    box.innerHTML = labels
      .map(function (label, i) {
        return (
          '<button type="button" data-topic="' + i + '" aria-label="Seek to chapter ' + esc(label) + '" ' +
          'class="flex items-center gap-2 px-2.5 py-1.5 rounded-full border border-slate-800 bg-slate-900/50 text-xs hover:border-violet-500/50 transition">' +
          '<span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:' + colors[i] + '" aria-hidden="true"></span>' +
          '<span class="font-medium truncate max-w-[10rem]">' + esc(label) + "</span>" +
          '<span class="font-mono text-gray-400">' + pcts[i] + "%</span></button>"
        );
      })
      .join("");
  }

  function setChartActive(i) {
    var chart = live.topicChart;
    if (!chart || typeof chart.setActiveElements !== "function") return;
    try {
      chart.setActiveElements(i === null ? [] : [{ datasetIndex: 0, index: i }]);
      chart.update();
    } catch (_) {
      /* best-effort highlight */
    }
  }

  function bindExport() {
    var btn = $("topicExport");
    if (!btn || btn._topicBound || typeof btn.addEventListener !== "function") return;
    btn._topicBound = true;
    btn.addEventListener("click", function () {
      var chart = live.topicChart;
      if (!chart || typeof chart.toBase64Image !== "function") return;
      if (typeof document === "undefined") return;
      var a = document.createElement("a");
      a.href = chart.toBase64Image("image/png", 1);
      a.download = "educlip-topics.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }

  // Legend badge interactions: hover links to chart + chapter list, click seeks.
  if (typeof document !== "undefined" && document.addEventListener && !window.__topicLegendBound) {
    window.__topicLegendBound = true;
    document.addEventListener("mouseover", function (e) {
      var b = e.target && e.target.closest ? e.target.closest("[data-topic]") : null;
      if (!b) return;
      var i = Number(b.getAttribute("data-topic"));
      setChartActive(i);
      highlightChapterRow(i, true);
    });
    var clearTopicHover = function (e) {
      var b = e.target && e.target.closest ? e.target.closest("[data-topic]") : null;
      if (!b) return;
      setChartActive(null);
      highlightChapterRow(Number(b.getAttribute("data-topic")), false);
    };
    document.addEventListener("mouseout", clearTopicHover);
    document.addEventListener("click", function (e) {
      var b = e.target && e.target.closest ? e.target.closest("[data-topic]") : null;
      if (b) seekSegment(Number(b.getAttribute("data-topic")));
    });
  }

  function renderTopicChart(payload) {
    var canvas = $("topicChart");
    if (!canvas || typeof Chart === "undefined") return false;
    applyDefaults();
    window.destroyCharts(["topicChart"]);
    var data = payload.data || { labels: [], datasets: [] };
    var labels = data.labels || [];
    var values = (((data.datasets || [])[0] || {}).data || []).map(function (v) {
      var n = Number(v);
      return isNaN(n) || n < 0 ? 0 : n;
    });
    var total = values.reduce(function (a, b) {
      return a + b;
    }, 0);
    // Guards: nothing to show, or a single chapter rendering a full ring.
    if (!labels.length || !values.length || total <= 0) {
      showCardState("topic", "pending");
      return false;
    }
    var pcts = values.map(function (v) {
      return Math.round((v / total) * 1000) / 10;
    });
    var colors = labels.map(function (_, i) {
      return TOPIC_COLORS[i % TOPIC_COLORS.length];
    });
    topicCtx = { values: values, labels: labels };
    var hoverRow = -1;
    var chart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "65%",
        onClick: function (evt, elements) {
          if (elements && elements.length) seekSegment(elements[0].index);
        },
        onHover: function (evt, elements) {
          if (hoverRow >= 0) highlightChapterRow(hoverRow, false);
          hoverRow = elements && elements.length ? elements[0].index : -1;
          if (hoverRow >= 0) highlightChapterRow(hoverRow, true);
          if (evt && evt.native && evt.native.target) {
            evt.native.target.style.cursor = elements && elements.length ? "pointer" : "default";
          }
        },
        plugins: {
          legend: { display: false },
          title: { display: true, text: "Time per chapter" },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var i = ctx.dataIndex;
                return " " + ctx.label + ": " + pcts[i] + "% · " + fmtDur(values[i]);
              },
            },
          },
        },
      },
    });
    live.topicChart = chart;
    canvas.setAttribute("role", "img");
    var top = 0;
    values.forEach(function (v, i) {
      if (v > values[top]) top = i;
    });
    canvas.setAttribute(
      "aria-label",
      "Doughnut chart of time per chapter. Largest: " + labels[top] + " at " + pcts[top] + " percent."
    );
    renderLegend(labels, pcts, colors);
    renderTableInto(
      "topicTable",
      "topicTableWrap",
      ["Chapter", "Share", "Time"],
      labels.map(function (label, i) {
        return [label, pcts[i] + "%", fmtDur(values[i])];
      })
    );
    showCardState("topic", "ready");
    bindExport();
    return true;
  }

  function pctStr(v) {
    return Math.round(Number(v) * 1000) / 10 + "%";
  }

  function renderPacingStats(values, labels, boundaryCount) {
    var box = $("pacingStats");
    if (!box) return;
    if (!values.length) {
      box.innerHTML = "";
      return;
    }
    var peak = 0;
    var sum = 0;
    values.forEach(function (v, i) {
      var n = Number(v) || 0;
      sum += n;
      if (n > Number(values[peak])) peak = i;
    });
    var avg = sum / values.length;
    function chip(k, v) {
      return (
        '<span class="px-2.5 py-1 rounded-full border border-slate-800 bg-slate-900/50 text-xs">' +
        '<span class="text-gray-500">' + esc(k) + " </span>" +
        '<span class="font-mono text-gray-200">' + esc(v) + "</span></span>"
      );
    }
    box.innerHTML =
      chip("Peak", pctStr(values[peak]) + " @ " + (labels[peak] || "")) +
      chip("Average", pctStr(avg)) +
      chip("Chapters marked", String(boundaryCount));
  }

  function renderPacingChart(payload) {
    var canvas = $("pacingChart");
    if (!canvas || typeof Chart === "undefined") return false;
    applyDefaults();
    window.destroyCharts(["pacingChart"]);
    var data = payload.data || { labels: [], datasets: [] };
    var labels = data.labels || [];
    var src = (data.datasets || [])[0] || {};
    var values = (src.data || []).map(function (v) {
      var n = Number(v);
      if (isNaN(n)) return 0;
      return Math.max(0, Math.min(1, n));
    });
    if (!labels.length || !values.length) {
      showCardState("pacing", "pending");
      return false;
    }
    // Chapter boundaries -> bucket labels for annotations + hover notes.
    var starts = getChapters()
      .map(function (c) {
        return { sec: Math.floor(Number(c.start_sec) || 0), title: c.title || "Untitled" };
      })
      .filter(function (s) {
        return s.sec >= 0 && Math.floor(s.sec / 60) < labels.length;
      });
    var startsByBucket = {};
    starts.forEach(function (s) {
      var b = Math.floor(s.sec / 60);
      (startsByBucket[b] = startsByBucket[b] || []).push(s.title);
    });
    var boundaryPlugin = {
      id: "pacingBoundaries",
      afterDatasetsDraw: function (chart) {
        var area = chart.chartArea;
        if (!area || !chart.scales || !chart.scales.x) return;
        var ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = "rgba(6,182,212,0.5)";
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        starts.forEach(function (s) {
          var label = labels[Math.floor(s.sec / 60)];
          var px = chart.scales.x.getPixelForValue(label);
          if (px < area.left || px > area.right) return;
          ctx.beginPath();
          ctx.moveTo(px, area.top);
          ctx.lineTo(px, area.bottom);
          ctx.stroke();
        });
        ctx.restore();
      },
    };
    var chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: src.label || "Attention score",
            data: values,
            borderColor: VIOLET,
            backgroundColor: "rgba(139,92,246,0.2)",
            fill: src.fill !== undefined ? src.fill : true,
            tension: 0.4,
            pointRadius: 2,
            pointHoverRadius: 5,
            pointBackgroundColor: VIOLET,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: function (evt, elements) {
          var i = elements && elements.length ? elements[0].index : null;
          if (i === null || i === undefined) return;
          var sec = labelToSec(labels[i]);
          if (typeof window.seekToTimestamp === "function") {
            window.seekToTimestamp(sec !== null ? sec : i * 60);
          }
        },
        onHover: function (evt, elements) {
          if (evt && evt.native && evt.native.target) {
            evt.native.target.style.cursor = elements && elements.length ? "pointer" : "default";
          }
        },
        plugins: {
          legend: { display: false },
          title: { display: true, text: "Attention curve" },
          tooltip: {
            callbacks: {
              title: function (items) {
                return items && items.length ? items[0].label + " min" : "";
              },
              label: function (ctx) {
                return " Attention " + pctStr(ctx.parsed.y);
              },
              afterBody: function (items) {
                if (!items || !items.length) return "";
                var names = startsByBucket[items[0].dataIndex] || [];
                return names.length ? "▶ " + names.join(", ") : "";
              },
            },
          },
        },
        scales: {
          x: { title: { display: true, text: "Video time (60s buckets)" } },
          y: { min: 0, max: 1, ticks: { callback: function (v) { return Math.round(v * 100) + "%"; } }, title: { display: true, text: "Attention" } },
        },
      },
      plugins: [boundaryPlugin],
    });
    live.pacingChart = chart;
    canvas.setAttribute("role", "img");
    var peak = 0;
    values.forEach(function (v, i) {
      if (v > values[peak]) peak = i;
    });
    canvas.setAttribute(
      "aria-label",
      "Line chart of attention over time. Peak " + pctStr(values[peak]) + " at " + labels[peak] + "."
    );
    renderPacingStats(values, labels, starts.length);
    renderTableInto(
      "pacingTable",
      "pacingTableWrap",
      ["Time", "Attention"],
      labels.map(function (label, i) {
        return [label, pctStr(values[i] !== undefined ? values[i] : 0)];
      })
    );
    showCardState("pacing", "ready");
    return true;
  }

  window.renderCharts = function (graphs, videoId) {
    var kw = graphs && graphs.keyword_density;
    var tp = graphs && graphs.chapter_duration;
    var pc = graphs && graphs.engagement_curve;
    var renderBoth = function () {
      if (kw && kw.data && !renderKeywordChart(kw)) showState("pending");
      if (tp && tp.data && !renderTopicChart(tp)) showCardState("topic", "pending");
      if (pc && pc.data && !renderPacingChart(pc)) showCardState("pacing", "pending");
    };
    if ((kw && kw.data) || (tp && tp.data) || (pc && pc.data)) {
      whenVisible($("keywordChartWrap") || $("topicChartWrap") || $("pacingChartWrap") || $("keywordChart"), renderBoth);
      return;
    }
    if (!videoId || typeof api === "undefined") {
      showState("pending");
      showCardState("topic", "pending");
      showCardState("pacing", "pending");
      return;
    }
    // Payload had no graphs — try the dedicated endpoint (backend order may vary).
    showState("loading");
    showCardState("topic", "loading");
    showCardState("pacing", "loading");
    api
      .get("/video/" + encodeURIComponent(videoId) + "/analytics")
      .then(function (data) {
        var g = (data && data.graphs) || data || {};
        var drew = false;
        if (g.keyword_density && g.keyword_density.data) drew = renderKeywordChart(g.keyword_density) || drew;
        else showState("pending");
        if (g.chapter_duration && g.chapter_duration.data) drew = renderTopicChart(g.chapter_duration) || drew;
        else showCardState("topic", "pending");
        if (g.engagement_curve && g.engagement_curve.data) drew = renderPacingChart(g.engagement_curve) || drew;
        else showCardState("pacing", "pending");
        return drew;
      })
      .catch(function () {
        showState("pending");
        showCardState("topic", "pending");
        showCardState("pacing", "pending");
      });
  };
})();
