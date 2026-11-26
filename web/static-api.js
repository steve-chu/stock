// 手機版：電腦版畫面原封不動，把它呼叫的 /api/... 改成讀 GitHub 每天算好的檔案（data/...）。
// 持股、交易紀錄只存在這支手機（localStorage），不會上傳。
(() => {
  const DATA = new URL(window.KP_DATA || 'data/', document.baseURI).href;   // 主題版（例如 bb/）共用上一層的資料
  const realFetch = window.fetch.bind(window);
  const KEY = 'kp.m.trades';
  let bust = Date.now();

  const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });
  const fail = (msg, status = 400) => json({ detail: msg }, status);
  const load = async p => {
    const r = await realFetch(DATA + p + '?t=' + bust, { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status === 404 ? '找不到資料（可能還沒更新到這檔）' : `HTTP ${r.status}`);
    return r.json();
  };

  // ---------- 交易紀錄（只在這支手機）----------
  const trades = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; } };
  const saveTrades = t => localStorage.setItem(KEY, JSON.stringify(t));
  window.kpTrades = { all: trades, save: saveTrades };

  // ---------- 持股計算：照電腦版 portfolio.py 一行一行搬過來 ----------
  const FEE_RATE = 0.001425, MIN_FEE_LOT = 20, MIN_FEE_ODD = 1;
  const taxRate = sid => sid.startsWith('00') ? 0.001 : 0.003;
  const fee = (amt, sh) => Math.max(Math.floor(amt * FEE_RATE), sh >= 1000 ? MIN_FEE_LOT : MIN_FEE_ODD);
  const tax = (amt, sid) => Math.floor(amt * taxRate(sid));
  const sellNet = (sid, p, sh) => { const a = p * sh; return a - fee(a, sh) - tax(a, sid); };
  const tick = p => p < 10 ? 0.01 : p < 50 ? 0.05 : p < 100 ? 0.1 : p < 500 ? 0.5 : p < 1000 ? 1 : 5;
  const r2 = x => Math.round(x * 100) / 100;
  const feeNote = sid => `手續費 0.1425%（不打折）、證交稅 ${taxRate(sid) * 100}%`;

  function replay(sid, list) {
    let shares = 0, cost = 0, realized = 0; const rows = [];
    for (const t of [...list].sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id)) {
      const amt = t.price * t.shares;
      if (t.side === 'buy') {
        const f = fee(amt, t.shares);
        shares += t.shares; cost += amt + f;
        rows.push({ ...t, fee: f, tax: 0, amount: Math.round(amt + f) });
      } else {
        if (t.shares > shares) return [null, `${t.date} 賣出 ${t.shares} 股，超過當時持有 ${shares} 股`];
        const avg = cost / shares, f = fee(amt, t.shares), tx = tax(amt, sid);
        const pnl = amt - f - tx - avg * t.shares;
        realized += pnl; cost -= avg * t.shares; shares -= t.shares;
        rows.push({ ...t, fee: f, tax: tx, amount: Math.round(amt - f - tx), pnl: Math.round(pnl) });
      }
      if (shares === 0) cost = 0;
    }
    return [{ shares, cost, realized: Math.round(realized), rows }, null];
  }

  function compute(sid, list, close, levels) {
    if (!list.length) return { has_position: false, trades: [], realized: 0, fee_note: feeNote(sid) };
    const [st, err] = replay(sid, list);
    if (err) return { has_position: false, error: err, trades: list, realized: 0, fee_note: feeNote(sid) };
    const out = { has_position: st.shares > 0, trades: [...st.rows].reverse(), realized: st.realized, fee_note: feeNote(sid) };
    if (st.shares <= 0) return out;
    const s = st.shares, cost = st.cost;
    const keep = 1 - FEE_RATE - taxRate(sid);
    let be = cost / (s * keep); const t = tick(be); be = Math.ceil(be / t - 1e-9) * t;
    const scen = (label, price, kind) => {
      if (price == null) return null;
      const net = sellNet(sid, price, s) - cost;
      return { label, price: r2(price), kind, net: Math.round(net), pct: r2(net / cost * 100), dist: r2((price / close - 1) * 100) };
    };
    const sc = [...levels.map(x => scen(...x)), scen('損益兩平', be, 'breakeven')].filter(Boolean)
      .sort((a, b) => a.price - b.price || (a.kind !== 'now') - (b.kind !== 'now'));
    const netNow = sellNet(sid, close, s) - cost;
    let hint = null;
    const stop = sc.find(x => x.kind === 'stop');
    const above = sc.filter(x => ['resistance', 'target'].includes(x.kind) && x.price > close * 1.002);
    if (stop && above.length) {
      const up = above[0].dist, dn = -stop.dist;
      if (dn > 0) {
        const ratio = up / dn;
        hint = ratio < 1 ? { tone: 'bear', text: `離上方壓力 ${up.toFixed(1)}%、離停損 ${dn.toFixed(1)}%，上檔空間小於下檔風險，不宜加碼` }
          : ratio >= 2 ? { tone: 'bull', text: `離上方壓力 ${up.toFixed(1)}%、離停損 ${dn.toFixed(1)}%，風險報酬 1:${ratio.toFixed(1)}，加碼條件較好` }
          : { tone: 'neutral', text: `離上方壓力 ${up.toFixed(1)}%、離停損 ${dn.toFixed(1)}%，風險報酬 1:${ratio.toFixed(1)}，普通` };
      }
    } else if (!above.length) hint = { tone: 'neutral', text: '股價已在所有壓力之上，用停損價或月線移動停利' };
    return Object.assign(out, {
      shares: s, lots: s / 1000, avg_cost: Math.round(cost / s * 1e4) / 1e4, total_cost: Math.round(cost),
      breakeven: r2(be), market_value: Math.round(close * s), unrealized: Math.round(netNow),
      unrealized_pct: r2(netNow / cost * 100), scenarios: sc, hint,
    });
  }

  // 從清單移除：只記在這支手機
  const HK = 'kp.m.hidden';
  const hidden = () => { try { return JSON.parse(localStorage.getItem(HK) || '[]'); } catch { return []; } };
  const setHidden = h => localStorage.setItem(HK, JSON.stringify([...new Set(h)]));
  window.kpHidden = { all: hidden, set: setHidden };
  // ★ 長期名單：每支手機自己決定（只記和預設不同的）
  const SK = 'kp.m.star';
  const stars = () => { try { return JSON.parse(localStorage.getItem(SK) || '{}'); } catch { return {}; } };
  let baseCore = {};   // 預設（stocks.txt 那邊）的 ★
  const isCore = sid => { const o = stars(); return sid in o ? o[sid] : !!baseCore[sid]; };
  const flipped = sid => isCore(sid) !== !!baseCore[sid];
  window.kpStar = {
    is: isCore,
    set(sid, on) { const o = stars(); if (on === !!baseCore[sid]) delete o[sid]; else o[sid] = on; localStorage.setItem(SK, JSON.stringify(o)); },
  };
  // 自選股順序：按住拖曳排的，只記在這支手機
  const OK = 'kp.m.order';
  const order = () => { try { return JSON.parse(localStorage.getItem(OK) || '[]'); } catch { return []; } };
  window.kpOrder = { set: ids => localStorage.setItem(OK, JSON.stringify(ids)), all: order };
  let allQuotes = [];
  window.kpAllQuotes = () => allQuotes;

  const heldSet = () => {
    const by = {};
    for (const t of trades()) (by[t.stock_id] = by[t.stock_id] || []).push(t);
    return new Set(Object.entries(by).filter(([sid, l]) => (replay(sid, l)[0] || {}).shares > 0).map(([sid]) => sid));
  };
  window.kpHeld = heldSet;

  async function watchlist() {
    const w = await load('watchlist.json'), held = heldSet(), hid = new Set(hidden());
    w.quotes.forEach(q => { baseCore[q.stock_id] = q.core; });
    allQuotes = w.quotes.map(q => (flipped(q.stock_id) ? { ...q, ...(q.alt || {}), core: !q.core } : q));
    const ord = order(), pos = id => { const i = ord.indexOf(id); return i < 0 ? 1e6 : i; };
    const sorted = allQuotes.map((q, i) => [q, i]).sort((a, b) => pos(a[0].stock_id) - pos(b[0].stock_id) || a[1] - b[1]).map(x => x[0]);
    const quotes = sorted.filter(q => !hid.has(q.stock_id)).map(q => {
      const h = held.has(q.stock_id);
      return { ...q, held: h, heat: h ? q._heat : null, crash: h ? q._crash : null, cooling: h ? !!q._cooling : false };
    });
    return { quotes, alerts: [] };
  }

  async function route(method, url, body) {
    const u = new URL(url, location.origin), p = u.pathname.replace(/^.*?\/api\//, ''), q = u.searchParams;
    let m;
    if (p === 'status') return json(await load('status.json'));
    if (p === 'watchlist' && method === 'GET') return json(await watchlist());
    if (p === 'refresh') {
      bust = Date.now();
      const w = await watchlist();
      const quiet = window.kpQuiet; window.kpQuiet = false;
      return json({ ...w, checked: w.quotes.length, fetched: 0, updated: [], failed: [], latest: quiet ? 0 : w.quotes.length });
    }
    if ((m = p.match(/^stock\/([^/]+)$/))) {
      if (q.get('as_of')) return fail('手機版沒有「回看」，要用的話請開電腦版');
      if (q.get('force')) bust = Date.now();
      const sid = decodeURIComponent(m[1]);
      let d;
      if (flipped(sid)) { try { d = await load(`stock/${sid}.alt.json`); } catch {} }
      if (!d) d = await load(`stock/${sid}.json`);
      const mine = trades().filter(t => t.stock_id === sid);
      d.portfolio = compute(sid, mine, d.bars[d.bars.length - 1].close, d.pf_levels || []);
      return json(d);
    }
    if ((m = p.match(/^bars\/([^/]+)$/))) return json(await load(`bars/${decodeURIComponent(m[1])}_${q.get('tf') || 'W'}.json`));
    if ((m = p.match(/^longbt\/([^/]+)$/))) return json(await load(`lbt/${decodeURIComponent(m[1])}.json`));
    if (p === 'longbt') return json(await load('lbt_all.json'));
    if (p === 'trades' && method === 'POST') {
      const t = JSON.parse(body || '{}');
      if (!/^\d{4}-\d\d-\d\d$/.test(t.date || '')) return fail('日期格式要是 YYYY-MM-DD');
      if (!(t.price > 0) || !(t.shares > 0)) return fail('價格和股數要大於 0');
      const all = trades(), id = Math.max(0, ...all.map(x => x.id)) + 1;
      const row = { id, stock_id: t.stock_id, date: t.date, side: t.side, price: t.price, shares: t.shares };
      const [, err] = replay(t.stock_id, [...all.filter(x => x.stock_id === t.stock_id), row]);
      if (err) return fail(err);
      saveTrades([...all, row]);
      return json({ id });
    }
    if ((m = p.match(/^trades\/(\d+)$/)) && method === 'DELETE') {
      saveTrades(trades().filter(t => t.id !== +m[1]));
      return json({ ok: true });
    }
    if ((m = p.match(/^watchlist\/([^/]+)$/)) && method === 'DELETE') {
      setHidden([...hidden(), decodeURIComponent(m[1])]);
      window.dispatchEvent(new Event('kp-hidden'));
      return json({ ok: true });
    }
    if (p === 'search') return json([]);
    if (['watchlist', 'settings', 'prefs', 'core'].some(k => p.startsWith(k)))
      return fail('手機版是唯讀的：自選股、分類、長期名單請在電腦版改，或改 GitHub 上的 stocks.txt');
    return fail('手機版沒有這個功能', 404);
  }

  window.fetch = async (input, opts = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!/^\/api\//.test(url)) return realFetch(input, opts);
    try { return await route((opts.method || 'GET').toUpperCase(), url, opts.body); }
    catch (e) { return fail(e.message || String(e), 502); }
  };
})();
