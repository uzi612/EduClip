/* static/js/theme.js — light/dark toggle. Dark is the default; preference persists. */

(function () {
  const KEY = "educlip-theme";

  function isDark() {
    try {
      return localStorage.getItem(KEY) !== "light";
    } catch (_) {
      return true;
    }
  }

  function paint() {
    const dark = isDark();
    document.documentElement.classList.toggle("dark", dark);
    const btn = document.getElementById("themeToggle");
    const moon = document.getElementById("iconMoon");
    const sun = document.getElementById("iconSun");
    if (btn) btn.setAttribute("aria-pressed", String(dark));
    if (moon) moon.classList.toggle("hidden", !dark);
    if (sun) sun.classList.toggle("hidden", dark);
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#themeToggle")) return;
    try {
      localStorage.setItem(KEY, isDark() ? "light" : "dark");
    } catch (_) {
      /* private mode: session-only toggle */
      document.documentElement.classList.toggle("dark");
      return;
    }
    paint();
  });

  paint();
})();
