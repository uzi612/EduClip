/* Node harness: executes static/js/api.js with stubbed browser globals. */
"use strict";
const fs = require("fs");
const Module = require("module");
const path = require("path");

const calls = [];
let queue = [];
let online = true;

function ok(data, status) {
  return { ok: (status || 200) < 400, status: status || 200, headers: { get: () => null }, json: async () => data };
}
function err(status, body, retryAfter) {
  return {
    ok: false, status: status,
    headers: { get: (k) => (k === "Retry-After" ? retryAfter : null) },
    json: async () => body,
  };
}

global.fetch = async (url, opts) => {
  calls.push({ url, opts });
  const next = queue.shift();
  if (next instanceof Error) throw next;
  return next;
};
Object.defineProperty(globalThis, "navigator", {
  value: { get onLine() { return online; } },
  configurable: true, writable: true,
});
function fakeEl() {
  return {
    children: [], className: "", textContent: "",
    setAttribute() {}, appendChild(c) { this.children.push(c); },
    remove() { this.removed = true; }, addEventListener() {},
  };
}
global.document = { getElementById: () => fakeEl(), createElement: () => fakeEl() };

const file = path.join(__dirname, "..", "..", "static", "js", "api.js");
const src = fs.readFileSync(file, "utf8") + "\nmodule.exports = { api, store, showToast, ApiError };";
const m = new Module(file, null);
m.filename = file;
m.paths = Module._nodeModulePaths(path.dirname(file));
m._compile(src, file);
const { api, store, showToast, ApiError } = m.exports;

let pass = 0, fail = 0;
async function t(name, fn) {
  calls.length = 0; queue = []; online = true;
  try { await fn(); pass++; console.log("PASS", name); }
  catch (e) { fail++; console.log("FAIL", name, "-", e.message); }
}
function eq(a, b, msg) {
  if (a !== b) throw new Error((msg || "") + " expected " + JSON.stringify(b) + " got " + JSON.stringify(a));
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

(async () => {
  await t("post sends Idempotency-Key + JSON", async () => {
    queue = [ok({ video_id: "abc", status: "processing" })];
    const d = await api.post("/process-video", { youtube_url: "https://youtu.be/dQw4w9WgXcQ" });
    eq(d.status, "processing");
    eq(calls.length, 1);
    eq(calls[0].opts.method, "POST");
    eq(calls[0].opts.headers["Content-Type"], "application/json");
    if (!UUID.test(calls[0].opts.headers["Idempotency-Key"])) throw new Error("bad uuid");
    eq(JSON.parse(calls[0].opts.body).youtube_url, "https://youtu.be/dQw4w9WgXcQ");
  });

  await t("get retries transient 503 then succeeds", async () => {
    queue = [err(503, { error: { code: "X", message: "boom" } }), ok({ status: "ready" })];
    const d = await api.get("/video/abc/");
    eq(d.status, "ready");
    eq(calls.length, 2);
  });

  await t("get gives up after retries on 500", async () => {
    queue = [err(500, {}), err(500, {}), err(500, {})];
    try { await api.get("/video/abc/"); throw new Error("should throw"); }
    catch (e) {
      eq(e instanceof ApiError, true);
      eq(e.code, "HTTP_500");
      eq(e.retryable, true);
      eq(calls.length, 3);
    }
  });

  await t("429 surfaces retry-after, no retry", async () => {
    queue = [err(429, { error: { code: "RATE_LIMITED", message: "Slow down." } }, "12")];
    try { await api.get("/video/abc/"); throw new Error("should throw"); }
    catch (e) {
      eq(e.status, 429); eq(e.code, "RATE_LIMITED");
      eq(e.retryAfterSec, 12); eq(e.retryable, true);
      eq(calls.length, 1);
    }
  });

  await t("offline short-circuits without fetch", async () => {
    online = false;
    try { await api.get("/video/abc/"); throw new Error("should throw"); }
    catch (e) { eq(e.code, "OFFLINE"); eq(calls.length, 0); }
  });

  await t("network error retries and recovers", async () => {
    queue = [new TypeError("fetch failed"), ok({ ok: true })];
    const d = await api.get("/health");
    eq(d.ok, true);
    eq(calls.length, 2);
  });

  await t("pollVideo resolves on ready with ticks", async () => {
    api.pollIntervalMs = 5;
    const ticks = [];
    queue = [
      ok({ status: "processing", progress: 0.2 }),
      ok({ status: "analyzing", progress: 0.7 }),
      ok({ status: "ready", video_id: "v1" }),
    ];
    const d = await api.pollVideo("v1", { onTick: (s, p) => ticks.push([s, p]) });
    eq(d.video_id, "v1");
    eq(JSON.stringify(ticks), JSON.stringify([["processing", 0.2], ["analyzing", 0.7]]));
    api.pollIntervalMs = 3000;
  });

  await t("pollVideo rejects failed with payload", async () => {
    api.pollIntervalMs = 5;
    queue = [ok({ status: "failed", error: { code: "NO_TRANSCRIPT", message: "No captions." } })];
    try { await api.pollVideo("v1"); throw new Error("should throw"); }
    catch (e) { eq(e.code, "NO_TRANSCRIPT"); eq(e.retryable, false); }
    api.pollIntervalMs = 3000;
  });

  await t("pollVideo times out", async () => {
    api.pollIntervalMs = 5; api.pollTimeoutMs = 20;
    queue = Array(10).fill(ok({ status: "processing", progress: 0.2 }));
    try { await api.pollVideo("v1"); throw new Error("should throw"); }
    catch (e) { eq(e.code, "POLL_TIMEOUT"); }
    api.pollIntervalMs = 3000; api.pollTimeoutMs = 5 * 60 * 1000;
  });

  await t("store.setVideo hydrates all sections", async () => {
    const seen = [];
    global.renderChapters = (c) => seen.push(["chapters", c]);
    global.destroyCharts = () => seen.push(["charts"]);
    global.window = { renderFlashcards: (l, id) => seen.push(["flash", l, id]) };
    store.setVideo({ video_id: "v9", chapters: [1], flashcards: [2] });
    eq(seen.length, 3);
    eq(seen[0][0], "charts"); // destroy-before-render first
    eq(seen[2][2], "v9");
    delete global.renderChapters; delete global.destroyCharts; delete global.window;
  });

  await t("store.setVideo skips flashcards when absent", async () => {
    let flashCalled = false;
    global.renderChapters = () => {};
    global.window = { renderFlashcards: () => { flashCalled = true; } };
    store.setVideo({ video_id: "v9", chapters: [] });
    eq(flashCalled, false);
    delete global.renderChapters; delete global.window;
  });

  await t("showToast renders retry action", async () => {
    let clicked = null;
    const wrapKids = [];
    global.document = {
      getElementById: () => ({ appendChild: (c) => wrapKids.push(c) }),
      createElement: () => fakeEl(),
    };
    showToast("Slow down.", "error", { label: "Retry", onClick: () => { clicked = true; } });
    const btn = wrapKids[0].children.find((c) => c.textContent === "Retry");
    if (!btn) throw new Error("no retry button");
  });

  await t("idempotency key falls back without randomUUID", async () => {
    const real = crypto.randomUUID;
    crypto.randomUUID = undefined;
    try {
      queue = [ok({ video_id: "abc", status: "processing" })];
      await api.post("/process-video", { youtube_url: "x" });
      if (!UUID.test(calls[0].opts.headers["Idempotency-Key"])) {
        throw new Error("bad fallback uuid: " + calls[0].opts.headers["Idempotency-Key"]);
      }
    } finally {
      crypto.randomUUID = real;
    }
  });

  console.log(pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
})();
