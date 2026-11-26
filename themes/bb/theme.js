// 貝貝版：文字加「貝貝」、小貓圖示、頭像、開場動畫。功能完全沿用主版本。
(() => {
  const $ = s => document.querySelector(s);
  const CAT = `<svg class="bb-cat" viewBox="0 0 64 64" aria-hidden="true">
    <path d="M10 26 8 6l16 10a26 24 0 0 1 16 0L56 6l-2 20a24 22 0 1 1-44 0Z" fill="#fff" stroke="#f3a6c8" stroke-width="2.5" stroke-linejoin="round"/>
    <path d="M13 21 12 12l8 6M51 21l1-9-8 6" fill="#ffb3cf"/>
    <circle cx="23" cy="34" r="3.4" fill="#5b3557"/><circle cx="41" cy="34" r="3.4" fill="#5b3557"/>
    <ellipse cx="17" cy="41" rx="4.5" ry="2.6" fill="#ffb3cf" opacity=".8"/><ellipse cx="47" cy="41" rx="4.5" ry="2.6" fill="#ffb3cf" opacity=".8"/>
    <path d="M29.5 39h5l-2.5 3Z" fill="#f0709f"/><path d="M32 42c-1.5 3-5 3-6 1M32 42c1.5 3 5 3 6 1" fill="none" stroke="#5b3557" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M44 10c3-4 9-1 6 4l-6 5-6-5c-3-5 3-8 6-4Z" fill="#f472b6"/></svg>`;

  // ---- 文字：前面加「貝貝」 ----
  document.title = '貝貝看盤台';
  const t = document.querySelector('title');
  if (t) new MutationObserver(() => { if (document.title.includes('我的看盤台')) document.title = document.title.replace('我的看盤台', '貝貝看盤台'); })
    .observe(t, { childList: true, characterData: true, subtree: true });
  const brandText = $('.brand > span'); if (brandText) brandText.textContent = '貝貝看盤台';
  const brandSvg = $('.brand > svg'); if (brandSvg) brandSvg.outerHTML = CAT;
  const h2 = $('.watch-head h2'); if (h2) h2.innerHTML = CAT + '貝貝自選股';
  const fixBack = () => { const b = $('.m-back'); if (b && b.lastChild && b.lastChild.nodeType === 3 && b.lastChild.textContent !== '貝貝自選股') b.lastChild.textContent = '貝貝自選股'; };
  fixBack();
  const holdTab = $('#tabs [data-tab="hold"]'); if (holdTab) holdTab.textContent = '貝貝的持股';
  const note = $('.m-note'); if (note) note.textContent = note.textContent.replace('資料每個交易日', '貝貝的資料每個交易日');

  // ---- 頭像（點一下再看一次開場） ----
  const av = document.createElement('button');
  av.type = 'button'; av.className = 'bb-avatar'; av.setAttribute('aria-label', '再看一次開場');
  av.style.backgroundImage = 'url("avatar.webp")';
  $('#refresh-all')?.after(av);
  av.addEventListener('click', () => splash(true));

  // ---- 清單最下面：小貓 ----
  const peek = document.createElement('div');
  peek.className = 'bb-peek'; peek.innerHTML = CAT.replace('class="bb-cat"', 'width="120" height="120"');
  $('.watch')?.append(peek);

  // ---- 開場：她的照片＋簽名，點一下才進主畫面 ----
  function splash(force) {
    try { if (!force && sessionStorage.getItem('bb.splash')) return; } catch {}
    const d = document.createElement('div');
    d.className = 'bb-splash';
    const spark = [[12, 18], [82, 12], [70, 78], [18, 72], [50, 8], [88, 46]]
      .map(([x, y], i) => `<span class="bb-sparkle" style="left:${x}%;top:${y}%;animation-delay:${i * .35}s">✦</span>`).join('');
    d.innerHTML = `${spark}
      <div class="bb-stage two"><img class="bb-photo" src="photo.webp" alt="">
        <div class="bb-sign">making money<br>makes me horny</div></div>
      <div class="bb-skip">點一下進入</div>`;
    document.body.append(d);
    d.addEventListener('click', () => {
      try { sessionStorage.setItem('bb.splash', '1'); } catch {}   // 點了才算看過
      d.classList.add('out'); setTimeout(() => d.remove(), 600);
    }, { once: true });
  }
  splash(false);
  new MutationObserver(fixBack).observe(document.querySelector('.top'), { childList: true, subtree: true, characterData: true });
})();
