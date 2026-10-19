(() => {
  const form = document.getElementById("sub");
  const url = document.getElementById("url");
  const open = document.getElementById("open");
  const copy = document.getElementById("copy");

  const build = () => {
    const picked = (name) => [...form.querySelectorAll(`input[name=${name}]:checked`)].map((i) => i.value).join(",");
    const q = new URLSearchParams();
    const tool = picked("tool");
    const company = picked("company");
    const min = form.elements.min.value;
    if (tool) q.set("tool", tool);
    if (company) q.set("company", company);
    if (min !== "1") q.set("min", min);
    const text = `${form.dataset.base}/feed.xml${q.toString() ? "?" + q : ""}`;
    url.value = text;
    open.href = text;
  };

  form.addEventListener("change", build);
  form.addEventListener("submit", (e) => e.preventDefault());
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(url.value);
      copy.textContent = "복사됨";
    } catch {
      url.select();
      copy.textContent = "직접 복사하세요";
    }
    setTimeout(() => (copy.textContent = "복사"), 1500);
  });
  build();
})();
