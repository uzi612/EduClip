/* Node harness: executes static/js/modal.js against a minimal fake DOM. */
"use strict";
const fs = require("fs");
const Module = require("module");

function matches(el, sel) {
  return sel.split(",").map((s) => s.trim()).some((part) => {
    if (part === "button") return el.tag === "button";
    if (part.startsWith("[") && part.endsWith("]") && !part.includes(":"))
      return part.slice(1, -1) in el._attrs;
    return false;
  });
}
function makeEl(tag, doc) {
  const el = {
    tag, children: [], className: "", textContent: "", parentNode: null,
    _attrs: {}, _listeners: {}, _html: "",
    set innerHTML(h) {
      this._html = h;
      const re = /<button\b([^>]*)>/g;
      let m;
      while ((m = re.exec(h))) {
        const b = makeEl("button", doc);
        if (m[1].includes("data-modal-close")) b._attrs["data-modal-close"] = "";
        if (m[1].includes("data-modal-retry")) b._attrs["data-modal-retry"] = "";
        b.parentNode = this;
        this.children.push(b);
      }
    },
    get innerHTML() { return this._html; },
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k]; },
    appendChild(c) { this.children.push(c); c.parentNode = this; },
    removeChild(c) {
      const i = this.children.indexOf(c);
      if (i >= 0) this.children.splice(i, 1);
      c.parentNode = null;
      return c;
    },
    addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); },
    remove() {
      if (this.parentNode) {
        const i = this.parentNode.children.indexOf(this);
        if (i >= 0) this.parentNode.children.splice(i, 1);
      }
      this.removed = true;
    },
    focus() { doc.activeElement = this; },
    closest(sel) { let n = this; while (n) { if (n.tag && matches(n, sel)) return n; n = n.parentNode; } return null; },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) {
      const out = [];
      const walk = (n) => (n.children || []).forEach((c) => { if (matches(c, sel)) out.push(c); walk(c); });
      walk(this);
      return out;
    },
  };
  return el;
}
function makeDoc() {
  const listeners = {};
  return {
    activeElement: null,
    body: makeEl("body", null),
    _listeners: listeners,
    createElement(tag) { return makeEl(tag, this); },
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
    removeEventListener(t, fn) { listeners[t] = (listeners[t] || []).filter((f) => f !== fn); },
    fire(t, e) { (listeners[t] || []).slice().forEach((f) => f(e)); },
  };
}

const doc = makeDoc();
doc.body.parentNode = null;
global.document = doc;
global.window = {};

const path = require("path");
const file = path.join(__dirname, "..", "..", "static", "js", "modal.js");
const src = fs.readFileSync(file, "utf8");
const m = new Module(file, null);
m._compile(src, file);
const { showModal, closeModal } = global.window;

let pass = 0, fail = 0;
function t(name, fn) {
  doc.body.children = [];
  doc.activeElement = null;
  try { fn(); pass++; console.log("PASS", name); }
  catch (e) { fail++; console.log("FAIL", name, "-", e.message); }
}
function eq(a, b, msg) {
  if (a !== b) throw new Error((msg || "") + " expected " + JSON.stringify(b) + " got " + JSON.stringify(a));
}

const invoker = makeEl("button", doc);

t("open renders alertdialog with title/message", () => {
  doc.activeElement = invoker;
  showModal({ title: "Taking too long", message: "Slow backend.", retryLabel: "Retry" });
  eq(doc.body.children.length, 1);
  const html = doc.body.children[0].innerHTML;
  if (!html.includes('role="alertdialog"')) throw new Error("missing role");
  if (!html.includes("Taking too long") || !html.includes("Slow backend.")) throw new Error("missing copy");
});

t("retry runs callback and closes", () => {
  let ran = false;
  doc.activeElement = invoker;
  showModal({ title: "T", message: "M", onRetry: () => { ran = true; } });
  const overlay = doc.body.children[0];
  const retry = overlay.querySelector("[data-modal-retry]");
  if (!retry) throw new Error("no retry btn");
  retry.parentNode._listeners.click.forEach((f) => f({ target: retry }));
  eq(ran, true);
  eq(doc.body.children.length, 0);
  eq(doc.activeElement, invoker); // focus restored
});

t("escape closes and detaches listener", () => {
  showModal({ title: "T", message: "M" });
  const before = (doc._listeners.keydown || []).length;
  doc.fire("keydown", { key: "Escape", preventDefault() {} });
  eq(doc.body.children.length, 0);
  eq((doc._listeners.keydown || []).length, before - 1);
});

t("tab traps focus inside dialog", () => {
  showModal({ title: "T", message: "M" });
  const overlay = doc.body.children[0];
  const btns = overlay.querySelectorAll("button");
  eq(btns.length >= 2, true);
  doc.activeElement = btns[btns.length - 1];
  doc.fire("keydown", { key: "Tab", shiftKey: false, preventDefault() {} });
  eq(doc.activeElement, btns[0]);
  doc.fire("keydown", { key: "Tab", shiftKey: true, preventDefault() {} });
  eq(doc.activeElement, btns[btns.length - 1]);
});

t("backdrop click closes", () => {
  showModal({ title: "T", message: "M" });
  const overlay = doc.body.children[0];
  const backdrop = { parentNode: overlay, closest: (s) => (s === "[data-modal-close]" ? {} : null) };
  overlay._listeners.click.forEach((f) => f({ target: backdrop }));
  eq(doc.body.children.length, 0);
});

console.log(pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
