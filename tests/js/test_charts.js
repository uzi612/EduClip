/* Node harness: executes static/js/charts.js with stubbed Chart + DOM. */
"use strict";
const fs = require("fs");
const Module = require("module");

function makeEl(tag, doc) {
  return {
    tag, children: [], className: "", textContent: "", parentNode: null,
    _attrs: {}, innerHTML: "", _listeners: {}, clicked: false,
    href: "", download: "",
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
      toggle(c, f) { if (f) this._s.add(c); else this._s.delete(c); },
    },
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k]; },
    appendChild(c) { this.children.push(c); },
    remove() {},
    addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); },
    click() { this.clicked = true; (this._listeners.click || []).forEach((f) => f()); },
  };
}

let ROWS = [];
const docListeners = {};
const doc = {
  activeElement: null,
  body: null,
  createElement(tag) { return makeEl(tag, doc); },
  getElementById(id) { return registry[id] || null; },
  querySelectorAll(sel) { return sel === ".chapter-row" ? ROWS : []; },
  addEventListener(t, fn) { (docListeners[t] = docListeners[t] || []).push(fn); },
  removeEventListener() {},
  fire(t, e) { (docListeners[t] || []).slice().forEach((f) => f(e)); },
};
doc.body = makeEl("body", doc);

const registry = {};
global.document = doc;

const sought = [];
global.window = {
  seekToTimestamp: (s) => sought.push(s),
  EDUCLIP: {},
};
global.api = { get: async () => { throw new Error("no endpoint"); } };

function StubChart(ctx, config) {
  StubChart.instances.push({ ctx, config });
  StubChart.made.push(this);
  this.config = config;
  this.destroyed = false;
}
StubChart.instances = [];
StubChart.made = [];
StubChart.prototype.destroy = function () { this.destroyed = true; };
StubChart.prototype.setActiveElements = function (els) { this.active = els; };
StubChart.prototype.update = function () { this.updated = (this.updated || 0) + 1; };
StubChart.prototype.toBase64Image = function () { return "data:image/png;base64,STUB"; };
StubChart.defaults = { font: {} };
global.Chart = StubChart;

const path = require("path");
const file = path.join(__dirname, "..", "..", "static", "js", "charts.js");
const m = new Module(file, null);
m._compile(fs.readFileSync(file, "utf8"), file);
const { renderCharts, destroyCharts } = global.window;

function canvasEl() {
  const c = makeEl("canvas", doc);
  return c;
}
function setupDom() {
  StubChart.instances = [];
  StubChart.made = [];
  sought.length = 0;
  for (const k of Object.keys(registry)) delete registry[k];
  registry.keywordChart = canvasEl();
  registry.keywordChartWrap = makeEl("div", doc);
  registry.keywordPending = makeEl("div", doc);
  registry.keywordTable = makeEl("table", doc);
  registry.keywordTableWrap = makeEl("details", doc);
  registry.topicChart = canvasEl();
  registry.topicChartWrap = makeEl("div", doc);
  registry.topicPending = makeEl("div", doc);
  registry.topicLegend = makeEl("div", doc);
  registry.topicExport = makeEl("button", doc);
  registry.topicTable = makeEl("table", doc);
  registry.topicTableWrap = makeEl("details", doc);
  registry.pacingChart = canvasEl();
  registry.pacingChartWrap = makeEl("div", doc);
  registry.pacingPending = makeEl("div", doc);
  registry.pacingStats = makeEl("div", doc);
  registry.pacingTable = makeEl("table", doc);
  registry.pacingTableWrap = makeEl("details", doc);
  ROWS = [makeEl("div", doc), makeEl("div", doc), makeEl("div", doc)];
  global.window.EDUCLIP = {};
}

const GRAPHS = {
  keyword_density: {
    type: "bar",
    data: {
      labels: ["0:00", "1:00", "2:00", "3:00"],
      datasets: [
        { label: "chlorophyll", data: [3, 5, 1, 0] },
        { label: "atp", data: [1, 2, 4, 1] },
      ],
    },
  },
};

const TOPIC = {
  chapter_duration: {
    type: "doughnut",
    data: {
      labels: ["Intro", "Deep dive", "Wrap"],
      datasets: [{ data: [60, 300, 60] }],
    },
  },
};

function badgeTarget(i) {
  return { closest: (sel) => (sel === "[data-topic]" ? { getAttribute: () => String(i) } : null) };
}

let pass = 0, fail = 0;
function t(name, fn) {
  setupDom();
  try { fn(); pass++; console.log("PASS", name); }
  catch (e) { fail++; console.log("FAIL", name, "-", e.message); }
}
function eq(a, b, msg) {
  if (JSON.stringify(a) !== JSON.stringify(b))
    throw new Error((msg || "") + " expected " + JSON.stringify(b) + " got " + JSON.stringify(a));
}

t("dark defaults applied", () => {
  renderCharts(GRAPHS);
  eq(StubChart.defaults.color, "#9ca3af");
  eq(StubChart.defaults.borderColor, "rgba(30,41,59,0.8)");
  eq(StubChart.defaults.font.family, "Inter");
});

t("bar config: colors, radius, legend, axes", () => {
  renderCharts(GRAPHS);
  eq(StubChart.instances.length, 1);
  const cfg = StubChart.instances[0].config;
  eq(cfg.type, "bar");
  eq(cfg.data.datasets[0].backgroundColor, "#8b5cf6");
  eq(cfg.data.datasets[1].backgroundColor, "#06b6d4");
  eq(cfg.data.datasets[0].borderRadius, 6);
  eq(cfg.options.plugins.legend.position, "bottom");
  eq(cfg.options.scales.y.beginAtZero, true);
  eq(cfg.options.responsive, true);
  eq(cfg.options.maintainAspectRatio, false);
});

t("bar click seeks bucket seconds", () => {
  renderCharts(GRAPHS);
  const onClick = StubChart.instances[0].config.options.onClick;
  onClick({}, [{ index: 2 }]);
  eq(sought, [120]);
  onClick({}, [{ index: 0 }]);
  eq(sought, [120, 0]);
});

t("non-60s label seeks parsed stamp", () => {
  const g = { keyword_density: { type: "bar", data: { labels: ["0:30", "2:15"], datasets: [{ label: "x", data: [1, 2] }] } } };
  renderCharts(g);
  StubChart.instances[0].config.options.onClick({}, [{ index: 1 }]);
  eq(sought, [135]);
});

t("re-render destroys previous chart", () => {
  renderCharts(GRAPHS);
  renderCharts(GRAPHS);
  eq(StubChart.made.length, 2);
  eq(StubChart.made[0].destroyed, true);
  eq(StubChart.made[1].destroyed, false);
});

t("destroyCharts kills all", () => {
  renderCharts(GRAPHS);
  destroyCharts();
  eq(StubChart.made[0].destroyed, true);
});

t("no graphs shows pending, no chart", () => {
  renderCharts(undefined, undefined);
  eq(StubChart.instances.length, 0);
  eq(registry.keywordPending.innerHTML.includes("Analytics pending"), true);
  eq(registry.keywordChartWrap.classList.contains("hidden"), true);
});

t("canvas gets a11y label + table rows", () => {
  renderCharts(GRAPHS);
  const aria = registry.keywordChart._attrs["aria-label"];
  if (!aria || !aria.includes("chlorophyll")) throw new Error("missing aria-label");
  eq(registry.keywordChart._attrs.role, "img");
  const rows = (registry.keywordTable.innerHTML.match(/<tr/g) || []).length;
  eq(rows, 5); // header + 4 buckets
  if (!registry.keywordTable.innerHTML.includes("atp")) throw new Error("missing dataset col");
});

t("tooltip shows counts", () => {
  renderCharts(GRAPHS);
  const label = StubChart.instances[0].config.options.plugins.tooltip.callbacks.label;
  eq(label({ dataset: { label: "atp" }, parsed: { y: 4 } }), " atp: 4 hits");
});

t("Chart undefined degrades to pending", () => {
  const saved = global.Chart;
  delete global.Chart;
  renderCharts(GRAPHS);
  global.Chart = saved;
  eq(StubChart.instances.length, 0);
  eq(registry.keywordPending.innerHTML.includes("Analytics pending"), true);
});

t("doughnut config: cutout, no border, palette", () => {
  renderCharts(TOPIC);
  eq(StubChart.instances.length, 1);
  const cfg = StubChart.instances[0].config;
  eq(cfg.type, "doughnut");
  eq(cfg.options.cutout, "65%");
  eq(cfg.data.datasets[0].borderWidth, 0);
  eq(cfg.data.datasets[0].backgroundColor.slice(0, 3), ["#8b5cf6", "#06b6d4", "#10b981"]);
  eq(cfg.options.plugins.legend.display, false);
  eq(cfg.options.plugins.title.text, "Time per chapter");
});

t("legend badges carry colors and shares", () => {
  renderCharts(TOPIC);
  const html = registry.topicLegend.innerHTML;
  ["data-topic=\"0\"", "data-topic=\"1\"", "data-topic=\"2\""].forEach((s) => {
    if (!html.includes(s)) throw new Error("missing " + s);
  });
  if (!html.includes("71.4%")) throw new Error("missing pct");
  if (!html.includes("Deep dive")) throw new Error("missing label");
  if (!html.includes("background:#8b5cf6")) throw new Error("missing color");
});

t("segment click seeks cumulative start", () => {
  renderCharts(TOPIC);
  const onClick = StubChart.instances[0].config.options.onClick;
  onClick({}, [{ index: 1 }]);
  onClick({}, [{ index: 2 }]);
  eq(sought, [60, 360]);
});

t("legend badge click seeks", () => {
  renderCharts(TOPIC);
  doc.fire("click", { target: badgeTarget(2) });
  eq(sought, [360]);
});

t("hover links chart segment to chapter row", () => {
  renderCharts(TOPIC);
  doc.fire("mouseover", { target: badgeTarget(0) });
  eq(ROWS[0].classList.contains("border-cyan-400/60"), true);
  eq(StubChart.made[0].active, [{ datasetIndex: 0, index: 0 }]);
  doc.fire("mouseout", { target: badgeTarget(0) });
  eq(ROWS[0].classList.contains("border-cyan-400/60"), false);
});

t("export downloads PNG", () => {
  let link = null;
  const origCreate = doc.createElement;
  doc.createElement = (tag) => {
    const el = origCreate(tag);
    if (tag === "a") link = el;
    return el;
  };
  const appended = [];
  const origAppend = doc.body.appendChild;
  doc.body.appendChild = (c) => { appended.push(c); return origAppend.call(doc.body, c); };
  renderCharts(TOPIC);
  registry.topicExport._listeners.click.forEach((f) => f());
  if (!link) throw new Error("no link created");
  eq(link.href, "data:image/png;base64,STUB");
  eq(link.download, "educlip-topics.png");
  eq(link.clicked, true);
});

t("single chapter renders full ring at 100%", () => {
  renderCharts({ chapter_duration: { type: "doughnut", data: { labels: ["Only"], datasets: [{ data: [420] }] } } });
  eq(StubChart.instances.length, 1);
  if (!registry.topicLegend.innerHTML.includes("100%")) throw new Error("missing 100%");
});

t("zero total shows pending, no chart", () => {
  renderCharts({ chapter_duration: { type: "doughnut", data: { labels: ["A", "B"], datasets: [{ data: [0, 0] }] } } });
  eq(StubChart.instances.length, 0);
  eq(registry.topicPending.innerHTML.includes("Analytics pending"), true);
});

t("topic table has share and time columns", () => {
  renderCharts(TOPIC);
  const rows = (registry.topicTable.innerHTML.match(/<tr/g) || []).length;
  eq(rows, 4); // header + 3 chapters
  if (!registry.topicTable.innerHTML.includes("71.4%")) throw new Error("missing share");
  if (!registry.topicTable.innerHTML.includes("5:00")) throw new Error("missing duration");
});

t("topic tooltip shows share and duration", () => {
  renderCharts(TOPIC);
  const label = StubChart.instances[0].config.options.plugins.tooltip.callbacks.label;
  eq(label({ dataIndex: 1, label: "Deep dive" }), " Deep dive: 71.4% · 5:00");
});

t("topic aria-label names largest share", () => {
  renderCharts(TOPIC);
  const aria = registry.topicChart._attrs["aria-label"];
  if (!aria || !aria.includes("Deep dive") || !aria.includes("71.4")) throw new Error("bad aria: " + aria);
  eq(registry.topicChart._attrs.role, "img");
});

t("renderCharts draws both charts together", () => {
  renderCharts({ keyword_density: GRAPHS.keyword_density, chapter_duration: TOPIC.chapter_duration });
  eq(StubChart.instances.length, 2);
});

const PACING = {
  engagement_curve: {
    type: "line",
    data: {
      labels: ["0:00", "1:00", "2:00", "3:00"],
      datasets: [{ label: "Attention score", data: [0.55, 0.85, 0.75, 0.7], fill: true }],
    },
  },
};
const CHAPTERS = [
  { start_sec: 0, title: "Intro" },
  { start_sec: 120, title: "Deep dive" },
];
function withChapters() {
  global.window.EDUCLIP = { chapters: CHAPTERS };
}

t("pacing config: violet line, fill, tension, y 0-1", () => {
  withChapters();
  renderCharts(PACING);
  eq(StubChart.instances.length, 1);
  const cfg = StubChart.instances[0].config;
  eq(cfg.type, "line");
  const ds = cfg.data.datasets[0];
  eq(ds.borderColor, "#8b5cf6");
  eq(ds.backgroundColor, "rgba(139,92,246,0.2)");
  eq(ds.fill, true);
  eq(ds.tension, 0.4);
  eq(cfg.options.scales.y.min, 0);
  eq(cfg.options.scales.y.max, 1);
  eq(cfg.options.plugins.legend.display, false);
  eq(cfg.options.plugins.title.text, "Attention curve");
});

t("pacing click seeks bucket stamp", () => {
  withChapters();
  renderCharts(PACING);
  const onClick = StubChart.instances[0].config.options.onClick;
  onClick({}, [{ index: 2 }]);
  eq(sought, [120]);
});

t("pacing stats row shows peak, average, marks", () => {
  withChapters();
  renderCharts(PACING);
  const html = registry.pacingStats.innerHTML;
  if (!html.includes("85%") || !html.includes("1:00")) throw new Error("missing peak: " + html);
  if (!html.includes("71.2%")) throw new Error("missing average: " + html);
  if (!html.includes("Chapters marked")) throw new Error("missing marks");
});

t("pacing tooltip previews chapter starts", () => {
  withChapters();
  renderCharts(PACING);
  const cb = StubChart.instances[0].config.options.plugins.tooltip.callbacks;
  eq(cb.label({ parsed: { y: 0.85 } }), " Attention 85%");
  eq(cb.afterBody([{ dataIndex: 2 }]), "▶ Deep dive");
  eq(cb.afterBody([{ dataIndex: 0 }]), "▶ Intro");
  eq(cb.afterBody([{ dataIndex: 1 }]), "");
});

t("boundary plugin draws chapter lines", () => {
  withChapters();
  renderCharts(PACING);
  const plugin = StubChart.instances[0].config.plugins.find((p) => p && p.id === "pacingBoundaries");
  if (!plugin) throw new Error("plugin not registered");
  const lines = [];
  const labels = ["0:00", "1:00", "2:00", "3:00"];
  const fake = {
    chartArea: { left: 0, right: 400, top: 0, bottom: 200 },
    scales: { x: { getPixelForValue: (l) => labels.indexOf(l) * 100 } },
    ctx: {
      save() {}, restore() {}, beginPath() {},
      moveTo(x, y) { this._x = x; }, lineTo(x, y) { lines.push([this._x, x]); },
      stroke() {}, setLineDash() {}, lineWidth: 0,
    },
  };
  plugin.afterDatasetsDraw(fake);
  eq(lines, [[0, 0], [200, 200]]);
});

t("pacing table lists time and attention", () => {
  withChapters();
  renderCharts(PACING);
  const rows = (registry.pacingTable.innerHTML.match(/<tr/g) || []).length;
  eq(rows, 5);
  if (!registry.pacingTable.innerHTML.includes("85%")) throw new Error("missing value");
});

t("pacing aria names the peak", () => {
  withChapters();
  renderCharts(PACING);
  const aria = registry.pacingChart._attrs["aria-label"];
  if (!aria || !aria.includes("85%") || !aria.includes("1:00")) throw new Error("bad aria: " + aria);
});

t("pacing empty labels shows pending", () => {
  withChapters();
  renderCharts({ engagement_curve: { type: "line", data: { labels: [], datasets: [{ data: [] }] } } });
  eq(StubChart.instances.length, 0);
  eq(registry.pacingPending.innerHTML.includes("Analytics pending"), true);
});

t("renderCharts draws all three together", () => {
  withChapters();
  renderCharts({
    keyword_density: GRAPHS.keyword_density,
    chapter_duration: TOPIC.chapter_duration,
    engagement_curve: PACING.engagement_curve,
  });
  eq(StubChart.instances.length, 3);
});

console.log(pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
