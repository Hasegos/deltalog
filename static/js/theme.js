/* =============================
  theme.js — 밝은 / 어두운 테마 전환
  처음에는 기기 설정(prefers-color-scheme)을 따르고, 버튼을 누르면 선택을 저장한다.
  ============================= */

(function () {
  const root = document.documentElement;
  const button = document.getElementById("theme-toggle");
  if (!button) return;

  function current() {
    return root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

  function paint() {
    const dark = current() === "dark";
    button.textContent = dark ? "☀" : "☾";
    button.setAttribute("aria-label", dark ? "밝은 테마로 바꾸기" : "어두운 테마로 바꾸기");
  }

  button.addEventListener("click", function () {
    const next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (e) {}
    paint();
  });
  paint();
})();

document.addEventListener("click", function (e) {
  const more = document.querySelector("details.more[open]");
  if (more && !more.contains(e.target)) more.removeAttribute("open");
});