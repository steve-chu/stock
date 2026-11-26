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

  // 擋掉 iOS 兩指縮放整個畫面（K 線自己的兩指縮放照常）
  ['gesturestart', 'gesturechange'].forEach(t => document.addEventListener(t, e => e.preventDefault(), { passive: false }));
  // 連點放大：CSS 的 touch-action 已經擋掉

  // 中間分隔線：拖拉調整 K 線和看板的比例（直放、橫放各自記住）
  const layout = document.querySelector('.layout');
  const split = document.createElement('div');
  split.className = 'm-split'; split.setAttribute('role', 'separator'); split.title = '拖拉調整比例，點兩下回到預設';
  document.querySelector('.side').before(split);
  const land = () => matchMedia('(orientation: landscape) and (max-height: 600px)').matches;
  const rKey = () => 'kp.m.ratio.' + (land() ? 'L' : 'P');
  const applyRatio = () => {
    let r = null; try { r = parseFloat(localStorage.getItem(rKey())); } catch {}
    if (r > 0) document.documentElement.style.setProperty('--m-r', r);
    else document.documentElement.style.removeProperty('--m-r');
  };
  applyRatio();
  let dragging = false;
  split.addEventListener('pointerdown', e => {
    dragging = true; split.classList.add('drag'); split.setPointerCapture(e.pointerId); e.preventDefault();
  });
  split.addEventListener('pointermove', e => {
    if (!dragging) return;
    const b = layout.getBoundingClientRect();
    let r = land() ? (e.clientX - b.left) / b.width : (e.clientY - b.top) / b.height;
    r = land() ? Math.min(.8, Math.max(.35, r)) : Math.min(.85, Math.max(.45, r));   // K 線區至少要留得下圖
    document.documentElement.style.setProperty('--m-r', r.toFixed(3));
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false; split.classList.remove('drag');
    try { localStorage.setItem(rKey(), getComputedStyle(document.documentElement).getPropertyValue('--m-r').trim()); } catch {}
    fixPanes(); fitTables();
  };
  split.addEventListener('pointerup', endDrag);
  split.addEventListener('pointercancel', endDrag);
  split.addEventListener('dblclick', () => { try { localStorage.removeItem(rKey()); } catch {} applyRatio(); fixPanes(); fitTables(); });

  // 表格太寬：整張等比縮小到看得完（最小縮到 6 成，再寬才左右滑）
  const fitTables = () => {
    document.querySelectorAll('.analysis table').forEach(t => {
      t.style.zoom = '';
      const box = t.parentElement, avail = box.clientWidth, w = t.scrollWidth;
      if (avail > 0 && w > avail + 1) t.style.zoom = Math.max(.6, (avail - 2) / w).toFixed(3);
    });
  };
  let fitTimer;
  const fitSoon = () => { clearTimeout(fitTimer); fitTimer = setTimeout(fitTables, 60); };
  new MutationObserver(fitSoon).observe(document.querySelector('.analysis'), { childList: true, subtree: true });
  document.querySelector('.analysis').addEventListener('toggle', fitSoon, true);

  // 轉向：重新套用比例、重新量圖表和表格；也把被 iOS 留下的縮放、捲動歸零
  const onRotate = () => { applyRatio(); window.scrollTo(0, 0); fixPanes(); setTimeout(fitTables, 120); setTimeout(fitTables, 500); };
  window.addEventListener('orientationchange', onRotate);
  matchMedia('(orientation: landscape)').addEventListener?.('change', onRotate);
  window.addEventListener('resize', fitSoon);

  // ---------- 對話框 ----------
  const dialog = (title, text, okText, danger) => new Promise(res => {
    const d = document.createElement('div');
    d.className = 'm-dlg';
    d.innerHTML = `<div class="m-dlg-box" role="dialog" aria-modal="true"><h3></h3><p></p>
      <div class="m-dlg-btns"><button type="button" data-a="0">取消</button><button type="button" data-a="1" class="${danger ? 'danger' : ''}"></button></div></div>`;
    d.querySelector('h3').textContent = title; d.querySelector('p').textContent = text;
    d.querySelector('[data-a="1"]').textContent = okText;
    d.addEventListener('click', e => {
      const b = e.target.closest('[data-a]');
      if (!b && e.target !== d) return;
      d.remove(); res(b?.dataset.a === '1');
    });
    document.body.append(d);
  });

  // ---------- 自選股：往左滑出現「移除」 ----------
  const wl = $('watchlist');
  const closeSwipes = except => wl.querySelectorAll('li.m-swiped').forEach(li => li !== except && li.classList.remove('m-swiped'));
  let sx = 0, sy = 0, sLi = null, swiping = false;
  wl.addEventListener('touchstart', e => {
    const t = e.touches[0]; sx = t.clientX; sy = t.clientY; sLi = e.target.closest('li[data-id]'); swiping = false;
  }, { passive: true });
  wl.addEventListener('touchmove', e => {
    if (!sLi || drag) return;
    const t = e.touches[0], dx = t.clientX - sx, dy = t.clientY - sy;
    if (Math.abs(dy) > 24 && !swiping) { sLi = null; return; }   // 是上下捲動
    if (dx < -40) { swiping = true; closeSwipes(sLi); sLi.classList.remove('m-star-hint'); sLi.classList.add('m-swiped'); }
    else if (dx > 40) {
      swiping = true;
      if (sLi.classList.contains('m-swiped')) { sLi.classList.remove('m-swiped'); sLi.dataset.closing = 1; }
      else if (!sLi.dataset.closing) sLi.classList.toggle('m-star-hint', dx > 70);   // 往右滑夠遠 → 放開就切換 ★
    }
  }, { passive: true });
  wl.addEventListener('touchend', () => {
    if (swiping) wl.dataset.justSwiped = Date.now();
    if (!drag && sLi?.classList.contains('m-star-hint')) { sLi.classList.remove('m-star-hint'); toggleStar(sLi.dataset.id); }
    if (sLi) delete sLi.dataset.closing;
    sLi = null;
  }, { passive: true });

  // ---------- 按住拖曳：排順序（只影響這支手機） ----------
  let lpTimer = null, drag = null, lpStart = [0, 0];
  const pageY = e => e.touches[0].clientY + window.scrollY;
  wl.addEventListener('touchstart', e => {
    const li = e.target.closest('li[data-id]');
    if (!li || li.classList.contains('m-swiped') || e.target.closest('[data-rm]')) return;
    const y0 = pageY(e), x0 = e.touches[0].clientX;
    clearTimeout(lpTimer);
    lpTimer = setTimeout(() => {
      closeSwipes(); li.classList.remove('m-star-hint');
      drag = { li, startY: y0, lastY: y0, top: li.offsetTop };
      li.classList.add('m-drag'); wl.classList.add('m-dragging');
      wl.dataset.justSwiped = Date.now();
      autoScroll();
    }, 380);
    lpStart = [x0, e.touches[0].clientY];
  }, { passive: true });
  const moveDrag = y => {
    const { li } = drag;
    drag.lastY = y;
    li.style.transform = `translateY(${y - drag.startY}px) scale(1.03)`;
    const r = li.getBoundingClientRect(), mid = r.top + r.height / 2;
    const next = li.nextElementSibling, prev = li.previousElementSibling;
    let moved = false;
    if (next && next.matches('li[data-id]') && mid > next.getBoundingClientRect().top + next.offsetHeight / 2) { wl.insertBefore(next, li); moved = true; }
    else if (prev && prev.matches('li[data-id]') && mid < prev.getBoundingClientRect().top + prev.offsetHeight / 2) { wl.insertBefore(li, prev); moved = true; }
    if (moved) {   // 換位後，修正起點讓手指下的那列不會跳
      const t = li.offsetTop; drag.startY += t - drag.top; drag.top = t;
      li.style.transform = `translateY(${y - drag.startY}px) scale(1.03)`;
    }
  };
  wl.addEventListener('touchmove', e => {
    if (!drag) {
      const t = e.touches[0];
      if (Math.hypot(t.clientX - lpStart[0], t.clientY - lpStart[1]) > 8) clearTimeout(lpTimer);   // 是滑動或捲動，不是按住
      return;
    }
    e.preventDefault();   // 拖曳中不要捲動整頁
    moveDrag(pageY(e));
  }, { passive: false });
  const endSort = () => {
    clearTimeout(lpTimer);
    if (!drag) return;
    const { li } = drag; drag = null;
    li.classList.remove('m-drag'); wl.classList.remove('m-dragging'); li.style.transform = '';
    wl.dataset.justSwiped = Date.now();
    const shown = [...wl.querySelectorAll('li[data-id]')].map(x => x.dataset.id);
    const rest = (window.kpAllQuotes?.() || []).map(q => q.stock_id).filter(id => !shown.includes(id));
    window.kpOrder?.set([...shown, ...rest]);
    reloadList();
  };
  wl.addEventListener('touchend', endSort);
  wl.addEventListener('touchcancel', endSort);
  // 拖到畫面上下緣時自動捲動
  const autoScroll = () => {
    if (!drag) return;
    const vy = drag.lastY - window.scrollY, H = window.innerHeight;
    const v = vy < 110 ? -10 : vy > H - 110 ? 10 : 0;
    if (v) { window.scrollBy(0, v); moveDrag(drag.lastY + v); }
    requestAnimationFrame(autoScroll);
  };

  // ★ 長期名單：往右滑加入／拿掉（只影響這支手機）
  const reloadList = () => {
    window.kpQuiet = true; $('refresh-all').click();
    setTimeout(() => { const t = $('toast'); if (t && !t.textContent.trim()) t.hidden = true; }, 350);   // 不要跳出空白提示
  };
  const toggleStar = async id => {
    if (!window.kpStar) return;
    const q = (window.kpAllQuotes?.() || []).find(x => x.stock_id === id) || {};
    const name = `${q.name || ''} ${id}`.trim();
    const on = window.kpStar.is(id);
    if (on && !await dialog(`把 ${name} 移出長期名單？`, '拿掉 ★ 後，這檔不再當成長期好股票，策略總表不會再給買點。只影響這支手機。', '移出', true)) return;
    window.kpStar.set(id, !on);
    reloadList();
    setTimeout(() => { try { toast(on ? `已把 ${name} 移出長期名單` : `★ 已把 ${name} 加入長期名單`); } catch {} }, 450);
  };

  let confirmed = null;
  wl.addEventListener('click', async e => {
    if (Date.now() - (+wl.dataset.justSwiped || 0) < 400) { e.stopPropagation(); e.preventDefault(); return; }
    const rm = e.target.closest('[data-rm]');
    if (rm) {
      const id = rm.dataset.rm;
      if (confirmed === id) return;           // 已確認：交給電腦版的程式移除
      e.stopPropagation(); e.preventDefault();
      const q = (window.kpAllQuotes?.() || []).find(x => x.stock_id === id) || {};
      const held = window.kpHeld?.().has(id);
      const name = `${q.name || ''} ${id}`.trim();
      if (q.core || held) {
        const why = [q.core && '在你的長期名單（★）', held && '你目前還有持股'].filter(Boolean).join('，');
        if (!await dialog(`確定移除 ${name}？`, `這檔${why}。移除後只是從這支手機的清單拿掉，持股紀錄不會刪，之後可以在清單最下面加回。`, '移除', true)) {
          closeSwipes(); return;
        }
      }
      confirmed = id;
      const click = () => wl.querySelector(`[data-rm="${CSS.escape(id)}"]`)?.click();
      click(); click();                       // 有持股時電腦版要按兩次才會移除
      confirmed = null;
      return;
    }
    if (wl.querySelector('li.m-swiped')) { closeSwipes(); e.stopPropagation(); e.preventDefault(); return; }
    if (e.target.closest('li[data-id]')) show('stock', true);   // 點一檔 → 進個股畫面
  }, true);

  // ---------- 被移除的：清單最下面可以加回 ----------
  const restore = document.createElement('button');
  restore.type = 'button'; restore.className = 'm-restore'; restore.hidden = true;
  document.querySelector('.watch').append(restore);
  const syncRestore = () => {
    const n = window.kpHidden?.all().length || 0;
    restore.hidden = !n; restore.textContent = `已從清單移除 ${n} 檔 · 加回`;
  };
  window.addEventListener('kp-hidden', syncRestore);
  restore.addEventListener('click', async () => {
    const ids = window.kpHidden.all(), all = window.kpAllQuotes?.() || [];
    const d = document.createElement('div');
    d.className = 'm-dlg';
    d.innerHTML = `<div class="m-dlg-box"><h3>加回清單</h3><ul class="m-hid">${ids.map(id => {
      const q = all.find(x => x.stock_id === id) || {};
      return `<li><span>${q.core ? '★ ' : ''}${q.name || ''} <small>${id}</small></span><button type="button" data-back="${id}">加回</button></li>`;
    }).join('')}</ul><div class="m-dlg-btns"><button type="button" data-all>全部加回</button><button type="button" data-close>關閉</button></div></div>`;
    const done = () => { d.remove(); syncRestore(); $('refresh-all').click(); };
    d.addEventListener('click', e => {
      const b = e.target.closest('[data-back]');
      if (b) { window.kpHidden.set(window.kpHidden.all().filter(x => x !== b.dataset.back)); b.closest('li').remove();
        if (!d.querySelector('[data-back]')) done(); return; }
      if (e.target.closest('[data-all]')) { window.kpHidden.set([]); done(); return; }
      if (e.target.closest('[data-close]') || e.target === d) done();
    });
    document.body.append(d);
  });
  setTimeout(syncRestore, 500);

  // 全部更新 → 手機版其實是「重新讀取 GitHub 今天算好的資料」
  const ra = $('refresh-all');
  ra.lastChild.remove();
  ra.insertAdjacentHTML('beforeend', '<span class="m-rt">重新整理</span>');
  ra.title = '重新讀取最新算好的資料（每個交易日傍晚自動更新）';

  // 清單下方說明
  const note = document.createElement('p');
  note.className = 'm-note';
  note.textContent = '按住拖曳可以排順序；往右滑加入／移出 ★ 長期名單，往左滑從清單移除（都只影響這支手機）。資料每個交易日傍晚自動更新一次。持股紀錄只存在這支手機，不會上傳；換手機或清除 Safari 資料會不見。';
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

  // 自動更新：手機會把首頁暫存起來，打開時比對伺服器上的版本，不同就換新的
  const myVer = document.querySelector('meta[name="kp-ver"]')?.content;
  // 這次載入是不是「自動更新」造成的（主題的開場用來判斷要不要再播）；網址上的 ?v= 用完就清掉
  try {
    const t = +localStorage.getItem('kp.m.autoReload') || 0;
    window.KP_AUTO_RELOADED = Date.now() - t < 20000;
    localStorage.removeItem('kp.m.autoReload');
  } catch {}
  if (/[?&]v=/.test(location.search)) history.replaceState(history.state, '', location.pathname);
  const checkVer = async () => {
    try {
      const r = await fetch((window.KP_DATA || 'data/') + 'version.json?t=' + Date.now(), { cache: 'no-store' });
      const { v } = await r.json();
      if (!myVer || !v || v === myVer || sessionStorage.getItem('kp.reloaded') === v) return;
      sessionStorage.setItem('kp.reloaded', v);
      try { localStorage.setItem('kp.m.autoReload', String(Date.now())); } catch {}
      location.replace(location.pathname + '?v=' + v);
    } catch {}
  };
  checkVer();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkVer(); });

  // 加到主畫面後開啟時，回到前景就重新讀一次（資料可能已經更新）
  let hiddenAt = 0;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (hiddenAt && Date.now() - hiddenAt > 30 * 60 * 1000) ra.click();
  });
})();
