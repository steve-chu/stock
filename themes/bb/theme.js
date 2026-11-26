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

  // ---- 開場：① 她的照片＋簽名（點一下）→ ② Loyalty Check（只能選 Yes）→ 主畫面 ----
  const SPARK = [[12, 18], [82, 12], [70, 78], [18, 72], [50, 8], [88, 46]]
    .map(([x, y], i) => `<span class="bb-sparkle" style="left:${x}%;top:${y}%;animation-delay:${i * .35}s">✦</span>`).join('');
  let showing = false;

  function splash(force) {
    if (showing) return;
    // 每次打開都出現；只有「剛看完、緊接著自動更新重新載入」那一次不再出現
    if (!force && window.KP_AUTO_RELOADED) {
      let at = 0; try { at = +localStorage.getItem('bb.splashAt') || 0; } catch {}
      if (Date.now() - at < 60 * 1000) return;
    }
    showing = true;
    const d = document.createElement('div');
    d.className = 'bb-splash';
    d.innerHTML = `${SPARK}
      <div class="bb-stage two"><img class="bb-photo" src="photo.webp" alt="">
        <div class="bb-sign">making money<br>makes me horny</div></div>
      <div class="bb-skip">Tap to continue</div>`;
    document.body.append(d);
    d.addEventListener('click', () => loyalty(d), { once: true });
  }

  function finish(d) {
    try { localStorage.setItem('bb.splashAt', String(Date.now())); } catch {}
    d.classList.add('out');
    setTimeout(() => { d.remove(); showing = false; }, 600);
  }

  const TAUNT = ['Hmm? Wrong button 🤨', 'Nice try, baby 😏', 'Are you SURE?? 😳', 'Last chance… 🥺'];

  function loyalty(d) {
    d.innerHTML = `${SPARK}
      <div class="bb-q">${CAT.replace('class="bb-cat"', 'class="bb-q-cat" width="68" height="68"')}
        <h2>Loyalty Check 💗</h2>
        <p>Will you stay loyal to Steve<br>forever &amp; ever?</p>
        <div class="bb-q-msg" aria-live="polite"></div></div>
      <button type="button" class="bb-yes">Yes, forever &amp; ever 💍</button>
      <button type="button" class="bb-no">No… I'd rather keep<br>my options open 🙈</button>`;
    const q = d.querySelector('.bb-q'), yes = d.querySelector('.bb-yes'), no = d.querySelector('.bb-no'), msg = d.querySelector('.bb-q-msg');
    let n = 0, ys = 1, done = false;
    const box = () => d.getBoundingClientRect();
    const place = (el, cx, cy) => { el.style.left = (cx - el.offsetWidth / 2) + 'px'; el.style.top = (cy - el.offsetHeight / 2) + 'px'; el._c = [cx, cy]; };
    const rectOf = (el, s) => { const [cx, cy] = el._c, w = el.offsetWidth * s, h = el.offsetHeight * s; return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]; };
    const hit = (a, b, m = 14) => !(a[2] + m < b[0] || b[2] + m < a[0] || a[3] + m < b[1] || b[3] + m < a[1]);
    // 在題目卡片下方的可用範圍裡，找一個隨機位置（不出螢幕、不壓到另一顆）
    const randomSpot = (el, s, avoid, farFrom) => {
      const B = box(), pad = 14, top = q.getBoundingClientRect().bottom - B.top + 16, bottom = B.height - 40;
      const w = el.offsetWidth * s, h = el.offsetHeight * s;
      let best = null;
      for (let i = 0; i < 60; i++) {
        const cx = pad + w / 2 + Math.random() * Math.max(1, B.width - w - pad * 2);
        const cy = top + h / 2 + Math.random() * Math.max(1, bottom - top - h);
        const r = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2];
        if (avoid && hit(r, avoid)) continue;
        if (farFrom && Math.hypot(cx - farFrom[0], cy - farFrom[1]) < 110) continue;
        best = [cx, cy]; break;
      }
      return best || [B.width / 2, (top + bottom) / 2];
    };
    // 一開始：Yes 在左、No 在右（太窄就上下排）
    requestAnimationFrame(() => {
      const B = box(), y0 = q.getBoundingClientRect().bottom - B.top + 70;
      if (yes.offsetWidth + no.offsetWidth + 40 < B.width) { place(yes, B.width * .3, y0); place(no, B.width * .7, y0); }
      else { place(yes, B.width / 2, y0); place(no, B.width / 2, y0 + 74); }
      d.classList.add('bb-ready');
    });

    const dodge = e => {
      e.preventDefault(); e.stopPropagation();
      if (done) return;
      n++;
      if (n >= 5) {   // 試了五次：No 直接不見，Yes 置中放大
        done = true;
        no.classList.add('gone');
        msg.textContent = 'You have NO choice. Be faithful 😡';
        msg.classList.add('mad');
        const B = box(); ys = Math.min(1.9, B.width * .88 / yes.offsetWidth); yes.style.transform = `scale(${ys})`;
        place(yes, B.width / 2, (q.getBoundingClientRect().bottom - B.top + B.height) / 2);
        return;
      }
      msg.textContent = TAUNT[n - 1];
      msg.classList.remove('pop'); void msg.offsetWidth; msg.classList.add('pop');
      // No 滑到別的地方（不會不見），Yes 跟著換位置、一次比一次大
      const noTo = randomSpot(no, 1, null, no._c);
      place(no, ...noTo);
      ys = Math.min(1 + n * 0.17, box().width * .8 / yes.offsetWidth);
      yes.style.transform = `scale(${ys})`;
      const yesTo = randomSpot(yes, ys, rectOf(no, 1));
      place(yes, ...yesTo);
    };
    no.addEventListener('pointerdown', dodge);
    no.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); });

    yes.addEventListener('click', e => {
      e.stopPropagation();
      msg.classList.remove('mad');
      msg.textContent = 'I knew it 💖';
      const B = box();
      for (let i = 0; i < 18; i++) {   // 愛心飛起來
        const h = document.createElement('span');
        h.className = 'bb-fly'; h.textContent = ['💖', '💕', '❤️', '💗'][i % 4];
        h.style.left = (B.width / 2 + (Math.random() - .5) * B.width * .8) + 'px';
        h.style.top = (B.height * .55 + Math.random() * 60) + 'px';
        h.style.animationDelay = (Math.random() * .3) + 's';
        d.append(h);
      }
      setTimeout(() => finish(d), 1100);
    }, { once: true });
  }
  splash(false);
  new MutationObserver(fixBack).observe(document.querySelector('.top'), { childList: true, subtree: true, characterData: true });
})();
