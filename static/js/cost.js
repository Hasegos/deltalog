(function () {
  var dataEl = document.getElementById("cost-data");
  var form = document.getElementById("cost-form");
  var body = document.getElementById("cost-rows");
  if (!dataEl || !form || !body) return;

  var data = JSON.parse(dataEl.textContent);
  var usd = new Intl.NumberFormat("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var krw = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

  function read(name) {
    var value = parseFloat(form.elements[name].value);
    return isFinite(value) && value >= 0 ? value : 0;
  }

  function cell(row, label, text, extraClass) {
    var td = row.insertCell();
    td.setAttribute("data-label", label);
    if (extraClass) td.className = extraClass;
    td.textContent = text;
    return td;
  }

  function render() {
    var tokensIn = read("in");
    var tokensOut = read("out");
    var requests = read("req");
    var fx = read("fx");
    var rows = data.models.map(function (m) {
      return { m: m, usd: ((tokensIn * m.in + tokensOut * m.out) / 1e6) * requests };
    });
    rows.sort(function (a, b) {
      return a.usd - b.usd || a.m.name.localeCompare(b.m.name);
    });

    body.textContent = "";
    rows.forEach(function (r) {
      var tr = body.insertRow();
      var name = cell(tr, "모델", "");
      var link = document.createElement("a");
      link.href = r.m.href;
      link.textContent = r.m.name;
      name.appendChild(link);
      var provider = document.createElement("span");
      provider.className = "md-pv";
      provider.textContent = " " + r.m.provider;
      name.appendChild(provider);
      var checked = document.createElement("small");
      checked.className = "md-nt";
      var source = document.createElement("a");
      source.href = r.m.source;
      source.target = "_blank";
      source.rel = "noopener";
      source.textContent = "가격 확인 " + r.m.verified + " ↗";
      checked.appendChild(source);
      name.appendChild(checked);
      if (r.m.note) {
        var note = document.createElement("small");
        note.className = "md-nt";
        note.textContent = "※ " + r.m.note;
        name.appendChild(note);
      }
      cell(tr, "월 비용 (USD)", "$" + usd.format(r.usd), "md-n");
      cell(tr, "월 비용 (원)", fx > 0 ? krw.format(r.usd * fx) + "원" : "환율을 입력하세요", "md-n");
    });
  }

  form.addEventListener("input", render);
  render();
})();