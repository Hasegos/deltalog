/* =============================
  home.js — 홈 목록 무한 스크롤 + 입력하는 즉시 검색
  - 무한 스크롤: "더 보기" 링크가 화면에 들어오면 다음 쪽 HTML을 받아 목록 뒤에 붙인다.
  - 즉시 검색: 검색창에 입력하면 잠깐 기다렸다가 같은 주소(?q=)의 HTML을 받아 본문을 바꾼다.
  JS가 없거나 실패해도 Enter와 "더 보기" 링크로 똑같이 쓸 수 있다.
  ============================= */

(function () {
  let observer = null;
  let loading = false;

  function initScroll() {
    if (observer) observer.disconnect();
    const list = document.querySelector(".list");
    const more = document.getElementById("more");
    if (!list || !more) return;

    observer = new IntersectionObserver(
      function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) {
          observer.unobserve(more);
          loadMore();
        }
      },
      { rootMargin: "400px 0px" }
    );
    more.addEventListener("click", function (e) {
      e.preventDefault();
      loadMore();
    });
    observer.observe(more);
  }

  function lastOf(list, selector, read) {
    const rows = list.querySelectorAll(selector);
    return rows.length ? read(rows[rows.length - 1]) : "";
  }

  async function loadMore() {
    const list = document.querySelector(".list");
    let more = document.getElementById("more");
    if (loading || !more) return;
    loading = true;
    more.classList.add("loading");
    more.textContent = "불러오는 중…";

    try {
      const res = await fetch(more.getAttribute("href"), { headers: { Accept: "text/html" } });
      if (!res.ok) throw new Error(res.status);

      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      let prev = lastOf(list, ".tr .mt span:first-child", function (n) { return n.textContent.trim(); });
      let prevWeek = lastOf(list, ".tr", function (n) { return n.dataset.week; });
      doc.querySelectorAll(".list > .wd, .list > .tr").forEach(function (node) {
        if (node.classList.contains("wd")) {
          if (node.dataset.week !== prevWeek) list.appendChild(document.importNode(node, true));
          return;
        }
        const date = node.querySelector(".mt span:first-child").textContent.trim();
        const dt = node.querySelector(".dt");
        if (dt && date === prev) dt.textContent = "";
        prev = date;
        prevWeek = node.dataset.week;
        list.appendChild(document.importNode(node, true));
      });

      const next = doc.getElementById("more");
      if (next) {
        more.setAttribute("href", next.getAttribute("href"));
        more.classList.remove("loading");
        more.textContent = "더 보기";
        observer.observe(more);
      } else {
        observer.disconnect();
        more.remove();
      }
    } catch (err) {
      more.classList.remove("loading");
      more.textContent = "다시 시도";
    } finally {
      loading = false;
    }
  }

  /* ── 즉시 검색 ── */
  const form = document.querySelector("form.sr");
  const input = form && form.querySelector('input[name="q"]');
  let timer = null;
  let controller = null;

  function queryString() {
    const params = new URLSearchParams();
    new FormData(form).forEach(function (value, key) {
      if (value) params.append(key, value);
    });
    return params.toString();
  }

  async function search() {
    const qs = queryString();
    const url = qs ? "/?" + qs : "/";
    if (controller) controller.abort();
    controller = new AbortController();
    const list = document.querySelector(".list");
    if (list) list.classList.add("busy");

    try {
      const res = await fetch(url, { headers: { Accept: "text/html" }, signal: controller.signal });
      if (!res.ok) throw new Error(res.status);
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const fresh = document.adoptNode(doc.querySelector("main"));
      fresh.querySelector("form.sr").replaceWith(form);
      document.querySelector("main").replaceWith(fresh);
      history.replaceState(null, "", url);
      loading = false;
      initScroll();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    } catch (err) {
      if (err.name !== "AbortError" && list) list.classList.remove("busy");
    }
  }

  if (form && input) {
    input.addEventListener("input", function (e) {
      if (e.isComposing) return;
      clearTimeout(timer);
      timer = setTimeout(search, 250);
    });
    input.addEventListener("compositionend", function () {
      clearTimeout(timer);
      timer = setTimeout(search, 250);
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      clearTimeout(timer);
      search();
    });
    document.addEventListener("keydown", function (e) {
      const tag = (document.activeElement && document.activeElement.tagName) || "";
      if (e.key === "/" && tag !== "INPUT" && tag !== "SELECT" && tag !== "TEXTAREA") {
        e.preventDefault();
        input.focus();
      }
    });
  }

  initScroll();
})();