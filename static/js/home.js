/* =============================
  home.js — 홈 목록 무한 스크롤
  "더 보기" 링크가 화면에 들어오면 다음 쪽 HTML을 받아 목록 뒤에 붙인다.
  JS가 없거나 실패해도 링크를 눌러 다음 쪽으로 갈 수 있다.
  ============================= */

(function () {
  const list = document.querySelector(".list");
  let more = document.getElementById("more");
  if (!list || !more) return;

  let loading = false;

  function lastDate() {
    const rows = list.querySelectorAll(".tr .mt span:first-child");
    return rows.length ? rows[rows.length - 1].textContent.trim() : "";
  }

  function lastWeek() {
    const rows = list.querySelectorAll(".tr");
    return rows.length ? rows[rows.length - 1].dataset.week : "";
  }

  async function loadMore() {
    if (loading || !more) return;
    loading = true;
    more.classList.add("loading");
    more.textContent = "불러오는 중…";

    try {
      const res = await fetch(more.getAttribute("href"), { headers: { Accept: "text/html" } });
      if (!res.ok) throw new Error(res.status);

      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      let prev = lastDate();
      let prevWeek = lastWeek();
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
        more = null;
      }
    } catch (err) {
      more.classList.remove("loading");
      more.textContent = "다시 시도";
    } finally {
      loading = false;
    }
  }

  const observer = new IntersectionObserver(
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
})();