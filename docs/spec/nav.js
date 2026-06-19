// 공유 사이드바 — 한 곳에서 정의, 각 페이지가 #sidebar에 주입. 활성 링크 자동 표시.
(function () {
  var NAV = [
    { grp: "개요", items: [["index.html", "Overview"]] },
    { grp: "역할별 문서", items: [
      ["pm.html", "🧭 기획자 · PRD"],
      ["dev.html", "🛠 개발자 · Tech Spec"],
      ["design.html", "🎨 디자이너 · Design"],
    ]},
    { grp: "공통 레퍼런스", items: [
      ["api.html", "API 레퍼런스"],
      ["stories.html", "유저스토리"],
      ["flows.html", "유저플로우"],
    ]},
  ];
  var here = location.pathname.split("/").pop() || "index.html";
  var html =
    '<a class="brand" href="index.html"><b>Oracle</b><span>제품 문서 · 역설계 스펙</span></a>';
  NAV.forEach(function (g) {
    html += '<div class="grp">' + g.grp + "</div>";
    g.items.forEach(function (it) {
      var active = it[0] === here ? " active" : "";
      html += '<a class="' + "link" + active + '" href="' + it[0] + '">' + it[1] + "</a>";
    });
  });
  html += '<div class="meta">자동 생성 · 정본=코드<br>github.com/cabechee/oracle</div>';
  var el = document.getElementById("sidebar");
  if (el) { el.className = "sidebar"; el.innerHTML = html; }

  // Mermaid (있으면) 초기화 — 다이어그램 페이지에서만 로드됨
  if (window.mermaid) {
    try {
      window.mermaid.initialize({
        startOnLoad: false, theme: "base", securityLevel: "loose",
        themeVariables: {
          fontFamily: "Pretendard, sans-serif", fontSize: "13px",
          primaryColor: "#FFFFFF", primaryBorderColor: "#BC4B33",
          primaryTextColor: "#161411", lineColor: "#9C988E",
          secondaryColor: "#F7ECE7", tertiaryColor: "#F6F4EE",
        },
      });
      if (window.mermaid.run) window.mermaid.run();
      else if (window.mermaid.init) window.mermaid.init();
    } catch (e) {}
  }
})();
