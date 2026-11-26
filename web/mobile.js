// 手機版外殼：清單 ↔ 個股 兩個畫面切換，加「‹ 自選股」返回鍵，狀態列顯示資料更新時間。
(() => {
  const $ = id => document.getElementById(id);
  const body = document.body;
  const show = (view, push) => {
    body.classList.toggle('m-list', view === 'list');
    body.classList.toggle('m-stock', view === 'stock');
    window.scrollTo(0, 0);
    if (view === 'stock') {
      if (push) history.pushState({ v: 'stock' }, '');
      fixPanes();   // 圖表從隱藏變顯示，讓它重新量尺寸
    }
  };
  show('list');
  history.replaceState({ v: 'list' }, '');

  // 分頁標籤黏在標題列下方：量標題列實際高度
  const top = document.querySelector('.top');
  new ResizeObserver(() => document.documentElement.style.setProperty('--top-h', top.offsetHeight + 'px')).observe(top);

  // 返回鍵
  const back = document.createElement('button');
  back.className = 'm-back'; back.type = 'button'; back.setAttribute('aria-label', '回自選股');
  back.innerHTML = '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>自選股';
  document.querySelector('.brand').prepend(back);
  back.addEventListener('click', () => (history.state?.v === 'stock' ? history.back() : show('list')));
  window.addEventListener('popstate', e => show(e.state?.v === 'stock' ? 'stock' : 'list'));

  // 個股畫面的版面：K線／一半／看板（記住上次的選擇）
  const fixPanes = () => [80, 350].forEach(ms => setTimeout(() => {
    window.dispatchEvent(new Event('resize'));
    try { setPaneHeights(); } catch {}
  }, ms));
  const modes = [['chart', 'K線'], ['split', '一半'], ['text', '看板']];
  const seg = document.createElement('div');
  seg.className = 'm-mode'; seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', '版面');
  seg.innerHTML = modes.map(([k, t]) => `<button type="button" data-mode="${k}">${t}</button>`).join('');
  back.after(seg);
  const setMode = m => {
    if (!modes.some(x => x[0] === m)) m = 'split';
    body.classList.toggle('v-chart', m === 'chart');
    body.classList.toggle('v-text', m === 'text');
    seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
    try { localStorage.setItem('kp.m.mode', m); } catch {}
    fixPanes();
  };
  seg.addEventListener('click', e => { const b = e.target.closest('[data-mode]'); if (b) setMode(b.dataset.mode); });
  let saved = 'split'; try { saved = localStorage.getItem('kp.m.mode') || 'split'; } catch {}
  setMode(saved);
  window.addEventListener('orientationchange', fixPanes);
  matchMedia('(orientation: landscape)').addEventListener?.('change', fixPanes);

  // 點清單任一檔 → 進個股畫面（電腦版的程式會負責載入那檔）
  $('watchlist').addEventListener('click', e => {
    if (e.target.closest('[data-rm]')) return;
    if (e.target.closest('li[data-id]')) show('stock', true);
  }, true);

  // 全部更新 → 手機版其實是「重新讀取 GitHub 今天算好的資料」
  const ra = $('refresh-all');
  ra.lastChild.remove();
  ra.insertAdjacentHTML('beforeend', '<span class="m-rt">重新整理</span>');
  ra.title = '重新讀取最新算好的資料（每個交易日傍晚自動更新）';

  // 清單下方說明
  const note = document.createElement('p');
  note.className = 'm-note';
  note.textContent = '資料每個交易日傍晚自動更新一次。持股紀錄只存在這支手機，不會上傳；換手機或清除 Safari 資料會不見。';
  document.querySelector('.watch').append(note);

  // 狀態列：補上「資料更新時間」
  let built = null;
  fetch('/api/status').then(r => r.json()).then(s => { built = s.built_at; tag(); }).catch(() => {});
  const st = $('status');
  const tag = () => {
    if (!built || st.querySelector('.m-built')) return;
    const b = document.createElement('span');
    b.className = 'at m-built'; b.textContent = ` · ${built.slice(5)} 更新`;
    st.append(b);
  };
  new MutationObserver(tag).observe(st, { childList: true });

  // 加到主畫面後開啟時，回到前景就重新讀一次（資料可能已經更新）
  let hiddenAt = 0;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (hiddenAt && Date.now() - hiddenAt > 30 * 60 * 1000) ra.click();
  });
})();
