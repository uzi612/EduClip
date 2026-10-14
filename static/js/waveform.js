/* static/js/waveform.js — glowing attention scrubber under the player.
   Uses the engagement_curve graph (same data as the pacing chart) plus
   chapter starts for tick marks. Click seeks; arrows seek ±10s.
   Depends on static/js/api.js (api). No other dependencies. */

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

  function bucketSec(labels, i, fallback) {
    var parts = String(labels[i] || "0:00").split(":");
    var secs = Number(parts[0]) * 60 + Number(parts[1] || 0);
    if (!isFinite(secs) || secs < 0) secs = i * (fallback || 60);
    return secs;
  }

  function renderWave(graphs, videoId, durationSec) {
    var wrap = $("waveWrap");
    var bar = $("waveBar");
    if (!wrap || !bar) return;
    var curve = graphs && graphs.engagement_curve;
    var data = curve && curve.data;
    var values = (data && data.datasets && data.datasets[0] && data.datasets[0].data) || [];
    var labels = (data && data.labels) || [];
    if (!values.length) {
      // Fall back to the dedicated endpoint (same pattern as charts/flashcards).
      if (videoId && typeof api !== "undefined") {
        api
          .get("/video/" + encodeURIComponent(videoId) + "/analytics")
          .then(function (res) {
            var g = (res && res.graphs) || {};
            renderWave(g, null, durationSec);
          })
          .catch(function () {
            wrap.classList.add("hidden");
          });
      } else {
        wrap.classList.add("hidden");
      }
      return;
    }
    var chapters = (window.EDUCLIP && window.EDUCLIP.chapters) || [];
    var max = 0;
    for (var i = 0; i < values.length; i++) {
      if (values[i] > max) max = values[i];
    }
    if (!max) max = 1;
    var ticks = chapters
      .map(function (c) {
        return Math.max(0, Math.floor(Number(c.start_sec) || 0));
      })
      .filter(function (t, idx, arr) {
        return arr.indexOf(t) === idx;
      });
    var html = values
      .map(function (v, idx) {
        var h = Math.max(8, Math.round((v / max) * 100));
        var sec = bucketSec(labels, idx, 60);
        return (
          '<span class="wave-cell" data-sec="' + sec + '" style="height:' + h + '%"' +
          ' title="' + fmtStamp(sec) + '"></span>'
        );
      })
      .join("");
    html += ticks
      .map(function (t) {
        var pct = durationSec > 0 ? Math.min(100, (t / durationSec) * 100) : 0;
        return (
          '<span class="wave-tick" data-sec="' + t + '" style="left:' + pct + '%"' +
          ' title="Chapter at ' + fmtStamp(t) + '"></span>'
        );
      })
      .join("");
    bar.innerHTML = html;
    bar.setAttribute("aria-valuemax", String(durationSec || 0));
    wrap.classList.remove("hidden");
  }

  function seekTo(sec) {
    if (typeof window.seekToTimestamp === "function") window.seekToTimestamp(sec);
    var bar = $("waveBar");
    if (bar) bar.setAttribute("aria-valuenow", String(Math.max(0, Math.floor(Number(sec) || 0))));
  }

  document.addEventListener("click", function (e) {
    var cell = e.target.closest ? e.target.closest(".wave-cell,.wave-tick") : null;
    if (!cell || !cell.closest("#waveBar")) return;
    seekTo(cell.getAttribute("data-sec"));
  });

  document.addEventListener("keydown", function (e) {
    var bar = $("waveBar");
    if (!bar || bar.classList.contains("hidden")) return;
    var focused = document.activeElement === bar;
    var inPlayer = e.target.closest && e.target.closest("#watchWrap");
    if (!focused && !inPlayer) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (typeof window.getPlayerTime !== "function") return;
    e.preventDefault();
    seekTo(window.getPlayerTime() + (e.key === "ArrowRight" ? 10 : -10));
  });

  window.renderWaveform = renderWave;
})();
