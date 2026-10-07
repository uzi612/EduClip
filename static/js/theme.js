/* static/js/theme.js — light/dark toggle. Dark is the default (v1); preference persists. */

(function () {
  const KEY = "educlip-theme";

  function isLight() {
    try {
      return localStorage.getItem(KEY) === "light";
    } catch (_) {
      return false;
    }
  }

  function paint() {
    const light = isLight();
    document.documentElement.classList.toggle("dark", !light);
    const btn = document.getElementById("themeToggle");
    const moon = document.getElementById("iconMoon");
    const sun = document.getElementById("iconSun");
    if (btn) btn.setAttribute("aria-pressed", String(light));
    if (moon) moon.classList.toggle("hidden", light);
    if (sun) sun.classList.toggle("hidden", !light);
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#themeToggle")) return;
    try {
      localStorage.setItem(KEY, isLight() ? "dark" : "light");
    } catch (_) {
      /* private mode: session-only toggle */
      document.documentElement.classList.toggle("dark");
      return;
    }
    paint();
  });

  paint();
})();
