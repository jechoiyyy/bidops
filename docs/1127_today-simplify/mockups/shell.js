// 시안 공통 사이드바·헤더. 본문은 각 시안의 <template id="body">에 있다.
document.addEventListener("DOMContentLoaded", () => {
  const body = document.getElementById("body").innerHTML;
  document.body.innerHTML = `
  <div class="app">
    <nav class="nav" aria-label="주 메뉴">
      <div class="logo"><i></i>BidOps</div>
      <a class="on" href="#"><span class="dot"></span>오늘 할 일</a>
      <div class="grp">탐색</div>
      <a href="#"><span class="dot"></span>발주계획<b>198</b></a>
      <a href="#"><span class="dot"></span>사전규격<b>101</b></a>
      <div class="grp"></div>
      <a href="#"><span class="dot"></span>사업기회</a>
      <a class="sub" href="#">최종 Go/No-Go</a>
      <div class="grp">관리</div>
      <a href="#"><span class="dot"></span>회사 근거<b>18</b></a>
      <a href="#"><span class="dot"></span>판정 기준</a>
      <a href="#"><span class="dot"></span>실행 상태</a>
      <div class="spacer"></div>
      <div class="snap"><strong>시연용 스냅샷</strong>2026. 11. 27. 13:00 KST 기준</div>
    </nav>
    <main class="main">
      <header class="top"><h1>오늘 할 일</h1>${document.body.dataset.top ?? ""}
        <div class="right"><a class="btn ghost" href="#">새로고침</a></div>
      </header>
      <div class="body">${body}</div>
    </main>
  </div>
  <div class="note">${document.title}</div>`;
});
