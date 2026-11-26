{
const LC = window.LightweightCharts;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = {
  up: css('--up'), down: css('--down'), line: css('--line'), mute: css('--mute'),
  ma5: css('--ma5'), ma20: css('--ma20'), ma60: css('--ma60'), accent: css('--accent'), warn: css('--warn'),
  cost: css('--cost'), ink: css('--ink'),
};
const $ = id => document.getElementById(id);
const store = {
  get(k, d) { try { const v = localStorage.getItem('kp.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('kp.' + k, JSON.stringify(v)); } catch {} },
};

const state = {
  list: [], current: null, data: null,
  range: store.get('range', 132), sub: store.get('sub', 'kd'),
  mas: { ma5: true, ma20: true, ma60: true, trend_ma: true, plan: true, cost: true, ...store.get('mas', {}) },
  tab: store.get('tab', 'tech'),
  side: 'buy', unit: store.get('unit', 'lot'), lbtY: store.get('lbtY', 3),
  overlay: null,            // {sec, item} 目前畫在圖上的說明
  asOf: null,               // 回看日期
  notify: store.get('notify', false),
  tf: store.get('tf', 'D'),
  tfBars: {}, tfBarsFor: {},
};
state.mas = { ma200: true, ma120: false, ma150: false, ma240: false, ...state.mas };

// ---------- helpers ----------
const fmt = (n, d = 2) => n == null || isNaN(n) ? '—' : Number(n).toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
const px = n => n == null ? '—' : fmt(n, n >= 1000 ? 0 : n >= 100 ? 1 : 2);
const pct = n => n == null ? '—' : (n > 0 ? '+' : '') + n.toFixed(2) + '%';
const cls = n => n > 0 ? 'up' : n < 0 ? 'down' : 'flat';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = n => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(Math.round(n)).toLocaleString('zh-TW');
const sharesTxt = s => s % 1000 === 0 ? `${(s / 1000).toLocaleString('zh-TW')} 張` : s >= 1000 ? `${Math.floor(s / 1000)} 張 ${s % 1000} 股` : `${s} 股`;
const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
const aIdx = d => { const i = d.bars.findIndex(b => b.date === d.analysis_date); return i < 0 ? d.bars.length - 1 : i; };
const abar = d => d.bars[aIdx(d)];
const lots = v => v >= 1000 ? Math.round(v / 1000).toLocaleString('zh-TW') + ' 張' : v + ' 股';

async function api(path, opts) {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch {}
  if (!r.ok) throw new Error(body?.detail || `HTTP ${r.status}`);
  return body;
}

// ---------- K 線週期（日／週／月），週、月 K 由日 K 合成 ----------
const TF_NAME = { D: '日', W: '週', M: '月' };
const MA_KEYS = ['ma5', 'ma20', 'ma60', 'ma120', 'ma150', 'ma200', 'ma240'];
const bucket = (date, tf) => {
  if (tf === 'D') return date;
  if (tf === 'M') return date.slice(0, 7) + '-01';
  const t = new Date(date + 'T00:00:00Z'), back = (t.getUTCDay() + 6) % 7;  // 每週一當代表日
  return new Date(t - back * 864e5).toISOString().slice(0, 10);
};
function aggregate(bars, tf) {
  const out = [];
  let cur = null;
  for (const b of bars) {
    const k = bucket(b.date, tf);
    if (!cur || cur.date !== k) {
      cur = { date: k, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume, last: b.date };
      out.push(cur);
    } else {
      cur.high = Math.max(cur.high, b.high); cur.low = Math.min(cur.low, b.low);
      cur.close = b.close; cur.volume += b.volume; cur.last = b.date;
    }
  }
  return out;
}
const jsma = (a, n) => { const o = Array(a.length).fill(null); let s = 0; a.forEach((v, i) => { s += v; if (i >= n) s -= a[i - n]; if (i >= n - 1) o[i] = s / n; }); return o; };
const jema = (a, n) => {
  const o = Array(a.length).fill(null), k = 2 / (n + 1); let prev = null, seed = [];
  a.forEach((v, i) => { if (v == null) return; if (prev == null) { seed.push(v); if (seed.length === n) { prev = seed.reduce((x, y) => x + y) / n; o[i] = prev; } return; } prev = v * k + prev * (1 - k); o[i] = prev; });
  return o;
};
function jind(bars) {
  const c = bars.map(b => b.close), h = bars.map(b => b.high), l = bars.map(b => b.low);
  const K = Array(c.length).fill(null), D = Array(c.length).fill(null);
  let k = 50, d = 50;
  for (let i = 8; i < c.length; i++) {
    const hh = Math.max(...h.slice(i - 8, i + 1)), ll = Math.min(...l.slice(i - 8, i + 1));
    const rsv = hh === ll ? 50 : (c[i] - ll) / (hh - ll) * 100;
    k = k * 2 / 3 + rsv / 3; d = d * 2 / 3 + k / 3; K[i] = k; D[i] = d;
  }
  const e12 = jema(c, 12), e26 = jema(c, 26);
  const dif = c.map((_, i) => e12[i] == null || e26[i] == null ? null : e12[i] - e26[i]);
  const dea = jema(dif, 9), hist = dif.map((v, i) => v == null || dea[i] == null ? null : v - dea[i]);
  const rsi = Array(c.length).fill(null);
  let ag = 0, al = 0;
  for (let i = 1; i < c.length; i++) {
    const g = Math.max(c[i] - c[i - 1], 0), ls = Math.max(c[i - 1] - c[i], 0);
    if (i <= 14) { ag += g / 14; al += ls / 14; if (i === 14) rsi[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al); }
    else { ag = (ag * 13 + g) / 14; al = (al * 13 + ls) / 14; rsi[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al); }
  }
  const ind = { k: K, d: D, dif, dea, hist, rsi, ma50: jsma(c, 50) };
  for (const m of MA_KEYS) ind[m] = jsma(c, +m.slice(2));
  return ind;
}

let V = null;  // 目前畫在圖上的資料（依日／週／月）

// 週 K、月 K 用長歷史（第一次會往前補抓，之後只更新新資料）
async function ensureTfBars(id, tf) {
  if (tf === 'D') return;
  const key = `${id}|${tf}`;
  if (state.tfBars[key] && state.tfBarsFor[key] === state.data?.bars.at(-1)?.date) return;
  const msg = $('chart-msg');
  const t = setTimeout(() => { msg.textContent = `第一次載入${TF_NAME[tf]} K 的長期歷史（最多 20 年），請稍候…`; msg.hidden = false; }, 400);
  try {
    const r = await api(`/api/bars/${encodeURIComponent(id)}?tf=${tf}`);
    state.tfBars[key] = r.bars;
    state.tfBarsFor[key] = state.data?.bars.at(-1)?.date;
    if (r.warning) toast(r.warning);
  } catch (e) {
    toast(`${TF_NAME[tf]} K 長歷史載入失敗，先用 5 年資料：${e.message}`);
  } finally {
    clearTimeout(t); msg.hidden = true;
  }
}

function syncMaAvailability() {
  // 算不出來的均線（資料年份不夠）把開關變灰
  document.querySelectorAll('#mas button[data-ma^="ma"]').forEach(b => {
    const arr = V?.ind[b.dataset.ma];
    const ok = !arr || arr.some(v => v != null);
    b.classList.toggle('na', !ok);
    const n = +b.dataset.ma.slice(2), unit = { D: '天', W: '週', M: '個月' }[V?.tf || 'D'];
    b.title = ok ? '' : `資料不足：${TF_NAME[V.tf]} K 的 MA${n} 需要 ${n} ${unit}的資料，這檔目前只有 ${V.bars.length} 根`;
  });
}
function buildView() {
  const d = state.data, tf = state.tf;
  if (tf === 'D') {
    const st = new Map((d.regime.stages || []).map(x => [x.date, x.s]));
    V = { tf, bars: d.bars, ind: d.indicators, dates: d.bars.map(b => b.date), ai: aIdx(d), stages: st,
          trendLabel: `趨勢 MA${d.regime.ma_period || 150}` };
    return;
  }
  const bars = state.tfBars[`${d.stock_id}|${tf}`] || aggregate(d.bars, tf), ind = jind(bars), c = bars.map(b => b.close);
  const dates = bars.map(b => b.date), ab = bucket(d.analysis_date, tf);
  const stages = new Map();
  let trendLabel = '';
  if (tf === 'W') {  // Weinstein 原版：30 週均線（依分類參數換算成週）
    const nw = Math.round((d.regime.ma_period || 150) / 5), sw = Math.max(1, Math.round((d.regime.slope_n || 20) / 5));
    const flat = d.regime.flat ?? 0.015, ma = jsma(c, nw);
    ind.trend_ma = ma;
    trendLabel = `趨勢 ${nw} 週均線`;
    ma.forEach((m, i) => {
      if (m == null || i < sw || ma[i - sw] == null || dates[i] > ab) return;
      const sl = m / ma[i - sw] - 1;
      stages.set(dates[i], c[i] > m && sl > flat ? 'bull' : c[i] < m && sl < -flat ? 'bear' : 'range');
    });
  } else {
    ind.trend_ma = Array(c.length).fill(null);
  }
  V = { tf, bars, ind, dates, ai: Math.max(0, dates.indexOf(ab)), stages, trendLabel };
}

// ---------- chart ----------
let chart, candle, vol, bg, markers, maSeries = {}, subSeries = [], planLines = [], overlayLines = [];
const STAGE_BG = { bull: 'rgba(242,70,78,0.24)', bear: 'rgba(29,185,120,0.24)', range: 'rgba(154,163,178,0.12)' };
const MA_COLOR = { ma50: '#fde68a', ma120: '#fb923c', ma150: '#38bdf8', ma200: '#f472b6', ma240: '#a3e635' };

function initChart() {
  chart = LC.createChart($('chart'), {
    autoSize: true,
    layout: {
      background: { type: 'solid', color: 'transparent' }, textColor: C.mute, fontSize: 12,
      fontFamily: css('--font'), panes: { separatorColor: C.line, enableResize: true },
      attributionLogo: false,
    },
    grid: { vertLines: { color: '#171b22' }, horzLines: { color: '#171b22' } },
    rightPriceScale: { borderColor: C.line },
    timeScale: { borderColor: C.line, rightOffset: 4, minBarSpacing: 1 },
    crosshair: { mode: LC.CrosshairMode.Normal },
    localization: { locale: 'zh-TW', timeFormatter: t => typeof t === 'string' ? t : typeof t === 'object' ? `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}` : new Date(t * 1000).toISOString().slice(0, 10) },
  });
  // 底色（Weinstein 階段、區間標示）要先加，才會畫在 K 線後面
  bg = chart.addSeries(LC.HistogramSeries, { priceScaleId: 'bg', priceLineVisible: false, lastValueVisible: false, base: 0 });
  chart.priceScale('bg').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
  candle = chart.addSeries(LC.CandlestickSeries, {
    upColor: C.up, downColor: C.down, borderUpColor: C.up, borderDownColor: C.down,
    wickUpColor: C.up, wickDownColor: C.down, priceLineColor: C.mute,
  });
  for (const k of ['ma5', 'ma20', 'ma60']) {
    maSeries[k] = chart.addSeries(LC.LineSeries, {
      color: C[k], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
  }
  for (const [k, col] of Object.entries(MA_COLOR)) {
    C[k] = col;
    maSeries[k] = chart.addSeries(LC.LineSeries, {
      color: col, lineWidth: k === 'ma200' || k === 'ma240' ? 2 : 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
  }
  markers = LC.createSeriesMarkers(candle, []);
  maSeries.trend_ma = chart.addSeries(LC.LineSeries, {
    color: C.ink + '99', lineWidth: 2, lineStyle: LC.LineStyle.Dashed, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false,
  });
  vol = chart.addSeries(LC.HistogramSeries, {
    priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false,
  }, 1);
  chart.subscribeCrosshairMove(p => updateLegend(p));
}

function line(arr, dates) {
  const out = [];
  arr.forEach((v, i) => { if (v != null) out.push({ time: dates[i], value: v }); });
  return out;
}

function setPaneHeights() {
  try {
    const panes = chart.panes();
    const h = $('chart').clientHeight;
    if (panes[1]) panes[1].setHeight(Math.round(h * 0.16));
    if (panes[2]) panes[2].setHeight(Math.round(h * 0.2));
  } catch {}
}

function drawSub() {
  if (!V) return;
  subSeries.forEach(s => chart.removeSeries(s));
  subSeries = [];
  const dates = V.dates, ind = V.ind;
  const add = (type, data, opts) => {
    const s = chart.addSeries(type, { priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, ...opts }, 2);
    s.setData(data); subSeries.push(s); return s;
  };
  if (state.sub === 'kd') {
    const k = add(LC.LineSeries, line(ind.k, dates), { color: C.ma5, lineWidth: 1, title: 'K' });
    add(LC.LineSeries, line(ind.d, dates), { color: C.ma20, lineWidth: 1, title: 'D' });
    k.createPriceLine({ price: 80, color: '#3a404c', lineStyle: LC.LineStyle.Dotted, axisLabelVisible: false });
    k.createPriceLine({ price: 20, color: '#3a404c', lineStyle: LC.LineStyle.Dotted, axisLabelVisible: false });
  } else if (state.sub === 'macd') {
    const hist = [];
    ind.hist.forEach((v, i) => { if (v != null) hist.push({ time: dates[i], value: v, color: v >= 0 ? C.up + 'b0' : C.down + 'b0' }); });
    add(LC.HistogramSeries, hist, { lastValueVisible: false, title: 'OSC' });
    add(LC.LineSeries, line(ind.dif, dates), { color: C.ma5, lineWidth: 1, title: 'DIF' });
    add(LC.LineSeries, line(ind.dea, dates), { color: C.ma20, lineWidth: 1, title: 'MACD' });
  } else {
    const r = add(LC.LineSeries, line(ind.rsi, dates), { color: C.ma60, lineWidth: 1, title: 'RSI14' });
    r.createPriceLine({ price: 70, color: '#3a404c', lineStyle: LC.LineStyle.Dotted, axisLabelVisible: false });
    r.createPriceLine({ price: 30, color: '#3a404c', lineStyle: LC.LineStyle.Dotted, axisLabelVisible: false });
  }
  setPaneHeights();
}

function drawPlan() {
  planLines.forEach(l => candle.removePriceLine(l));
  planLines = [];
  const s = state.data?.strategy, pos = state.data?.portfolio;
  const add = (price, color, title, style = LC.LineStyle.Dashed, w = 1) => {
    if (price == null) return;
    planLines.push(candle.createPriceLine({ price, color, title, lineStyle: style, lineWidth: w, axisLabelVisible: true }));
  };
  if (s && state.mas.plan) {
    const col = { tranche: '#60a5fa', entry: C.accent, stop: C.warn, target: C.ma60 };
    for (const x of s.lines || []) add(x.price, col[x.kind] || C.ink, x.label, x.kind === 'tranche' ? LC.LineStyle.LargeDashed : LC.LineStyle.Dashed);
  }
  if (pos?.has_position && state.mas.cost) {
    add(pos.avg_cost, C.cost, '成本', LC.LineStyle.Solid, 2);
    add(pos.breakeven, C.cost, '兩平', LC.LineStyle.Dotted);
  }
}

function drawChart() {
  const d = state.data;
  buildView();
  const bars = V.bars, dates = V.dates;
  candle.applyOptions({ lastValueVisible: !d.replay, priceLineVisible: !d.replay });  // 回看時不顯示「最新價」那條線
  candle.setData(bars.map(b => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close })));
  vol.setData(bars.map((b, i) => ({
    time: b.date, value: b.volume / 1000,
    color: (i && b.close < bars[i - 1].close ? C.down : C.up) + '70',
  })));
  for (const k of [...MA_KEYS, 'ma50', 'trend_ma']) maSeries[k].setData(line(V.ind[k] || [], dates));
  syncMaAvailability();
  drawSub();
  drawPlan();
  drawOverlay(false);
  applyRange();
  updateLegend();
}

const RANGE_DIV = { D: 1, W: 5, M: 21 };
function applyRange() {
  if (!V) return;
  const n = V.bars.length;
  if (!n) return;
  if (!state.range) return chart.timeScale().fitContent();
  const r = Math.max(6, Math.round(state.range / RANGE_DIV[V.tf]));
  if (state.data.replay) {  // 回看：回看日放在畫面約 2/3 處，右邊看得到之後的走勢
    return chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, V.ai - r * 0.7), to: Math.min(n + 3, V.ai + r * 0.35) });
  }
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - r), to: n + 3 });
}

function updateLegend(p) {
  if (!V || !state.data) return;
  let i = V.ai;
  if (p && p.time) {
    const t = typeof p.time === 'string' ? p.time : `${p.time.year}-${String(p.time.month).padStart(2, '0')}-${String(p.time.day).padStart(2, '0')}`;
    const j = V.dates.indexOf(t);
    if (j >= 0) i = j;
  }
  const b = V.bars[i], prev = V.bars[i - 1] || b, ind = V.ind;
  const c = cls(b.close - prev.close);
  const pre = V.tf === 'D' ? '' : TF_NAME[V.tf];
  const ma = k => state.mas[k] && ind[k]?.[i] != null ? `<span style="color:${C[k]}">${pre}${k.toUpperCase()}<b>${px(ind[k][i])}</b></span>` : '';
  const when = V.tf === 'D' ? b.date : V.tf === 'W' ? `${b.date} 當週` : b.date.slice(0, 7);
  $('legend').innerHTML =
    `<span>${when}</span><span>開<b>${px(b.open)}</b></span><span>高<b>${px(b.high)}</b></span>` +
    `<span>低<b>${px(b.low)}</b></span><span>收<b class="${c}">${px(b.close)}</b></span>` +
    `<span>量<b>${lots(b.volume)}</b></span>${MA_KEYS.map(ma).join('')}` +
    (state.mas.trend_ma && ind.trend_ma?.[i] != null ? `<span>${V.trendLabel}<b>${px(ind.trend_ma[i])}</b></span>` : '');
}

async function setTF(tf, redraw = true) {
  if (state.tf === tf) return false;
  state.tf = tf; store.set('tf', tf); syncButtons();
  if (state.data) await ensureTfBars(state.data.stock_id, tf);
  if (redraw && state.data) drawChart();
  return true;
}

// ---------- 圖上標記（點分析文字時畫出來） ----------
// 點哪一個方法，自動切到最適合它的 K 線
const OV_TF = { weinstein: 'W', zone: 'W', wyckoff: 'D', minervini: 'D', danger: 'D', retail: 'D', lbt: 'D' };

function currentOverlay() {
  const d = state.data, o = state.overlay;
  if (!d || !o) return null;
  if (o.sec === 'zone') {
    const z = (d.zones[o.kind] || [])[o.item];
    if (!z) return null;
    const lab = o.kind === 'panic' ? '恐慌區' : '壓力區';
    return { lines: Math.abs(z.hi - z.lo) / z.hi < 0.003 ? [{ price: z.mid ?? z.hi, label: lab }] : [{ price: z.hi, label: lab + '上緣' }, { price: z.lo, label: lab + '下緣' }],
             color: o.kind === 'panic' ? C.down : C.up };
  }
  if (o.sec === 'danger') {
    const sg = d.danger.signals?.[o.item];
    const short = { dist: '出貨', div: '背離', vdiv: '量背離', climax: '爆量' }[sg?.key] || '';
    return sg ? { markers: sg.dates.map(t => ({ date: t, text: short, pos: 'above' })) } : null;
  }
  if (o.sec === 'lbt') {   // 長線回測的買點：回升段紅色▲在 K 棒下方、恐慌段綠色▼在 K 棒上方，都指著買進那根
    const ts = state.lbt?.[d.stock_id]?.trades?.[o.kind];
    if (!ts) return null;
    return { markers: ts.map(t => t.side === 'up'
      ? { date: t.date, pos: 'below', text: '▲ ' + t.label, color: C.up, size: 2 }
      : { date: t.date, pos: 'above', text: '▼ ' + t.label, color: C.down, size: 2 }) };
  }
  if (o.sec === 'retail') {
    const sg = d.retail.signals?.[o.item];
    return sg?.date ? { markers: [{ date: sg.date, text: sg.label, pos: 'above' }], date: sg.date } : null;
  }
  const sec = d.regime.sections?.find(x => x.key === o.sec);
  if (!sec) return null;
  if (o.item == null) {
    const ov = sec.overlay || {};
    return { series: ov.series || [], lines: ov.lines || [], markers: ov.markers || [], shade: !!ov.shade, from: ov.from };
  }
  const dr = sec.items[o.item]?.draw || {};
  return { series: dr.keys || [], lines: dr.lines || (dr.line ? [dr.line] : []), date: dr.date,
           range: dr.type === 'range' ? dr.date : null };
}

function syncSeriesVisibility() {
  const forced = new Set(currentOverlay()?.series || []);
  for (const k of [...MA_KEYS, 'trend_ma']) maSeries[k].applyOptions({ visible: !!state.mas[k] || forced.has(k) });
  maSeries.ma50.applyOptions({ visible: forced.has('ma50') });
}

function drawOverlay(scroll = true) {
  const d = state.data; if (!d || !V) return;
  overlayLines.forEach(l => candle.removePriceLine(l)); overlayLines = [];
  const ov = currentOverlay();
  syncSeriesVisibility();
  const B = t => bucket(t, V.tf), dates = V.dates, have = new Set(dates), aday = B(d.analysis_date);
  let bgData = [];
  if (ov?.shade) {
    bgData = dates.filter(t => V.stages.has(t)).map(t => ({ time: t, value: 1, color: STAGE_BG[V.stages.get(t)] }));
  } else if (ov?.range || ov?.from) {
    const from = B(ov.range || ov.from);
    bgData = dates.filter(t => t >= from && t <= aday).map(t => ({ time: t, value: 1, color: 'rgba(77,141,255,0.13)' }));
  }
  bg.setData(bgData);
  for (const l of ov?.lines || []) {
    if (l.price == null) continue;
    overlayLines.push(candle.createPriceLine({ price: l.price, color: ov.color || C.ink, lineStyle: LC.LineStyle.Dashed,
                                               lineWidth: 1, title: l.label, axisLabelVisible: true }));
  }
  const ms = [], seen = new Set();
  const push = m => { const k = m.time + m.text + m.position; if (!seen.has(k) && have.has(m.time)) { seen.add(k); ms.push(m); } };
  if (d.replay) push({ time: aday, position: 'aboveBar', color: C.accent, shape: 'arrowDown', text: '回看日' });
  for (const m of ov?.markers || []) {
    if (m.date) push({ time: B(m.date), position: m.pos === 'above' ? 'aboveBar' : 'belowBar',
      color: m.color || C.ink, shape: m.pos === 'above' ? 'arrowDown' : 'arrowUp', text: m.text, ...(m.size ? { size: m.size } : {}) });
  }
  if (ov?.date) push({ time: B(ov.date), position: 'belowBar', color: C.warn, shape: 'circle', text: '起點' });
  ms.sort((x, y) => (x.time < y.time ? -1 : x.time > y.time ? 1 : 0));
  markers.setMarkers(ms);
  if (scroll && ov) {
    const t = ov.date || ov.range || ov.from, i = t ? dates.indexOf(B(t)) : -1, end = V.ai;
    const pad = { D: 30, W: 12, M: 6 }[V.tf];
    if (i >= 0) chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, Math.min(i, end) - pad), to: Math.max(i, end) + pad / 2 });
    else if (ov.shade) chart.timeScale().fitContent();
  }
  document.querySelectorAll('[data-ov]').forEach(el => {
    const o = state.overlay;
    el.classList.toggle('active', !!o && el.dataset.ov === `${o.sec}|${o.kind ?? ''}|${o.item ?? ''}`);
  });
  const clr = $('ov-clear'); if (clr) clr.hidden = !state.overlay;
}

async function toggleOverlay(o) {
  const key = x => x && `${x.sec}|${x.kind ?? ''}|${x.item ?? ''}`;
  state.overlay = key(state.overlay) === key(o) ? null : o;
  const want = state.overlay && OV_TF[state.overlay.sec];
  if (want && await setTF(want, false)) {
    drawChart();
    if (state.overlay.sec !== 'lbt') toast(`已切到${TF_NAME[want]} K：${{ W: '看長線趨勢、恐慌區比較清楚', D: '這個判斷要看每天的量價' }[want]}`, 2500);
  }
  drawOverlay(true);
  if (state.overlay?.sec === 'lbt') {   // 回測買點：日 K、看近一年
    state.range = 250; store.set('range', 250); syncButtons(); applyRange();
  }
  if (state.tab === 'tech' && (o.sec === 'lbt')) renderTech();
}

// ---------- 技術分析 tab ----------
const TONE = { bull: 't-bull', bear: 't-bear', wash: 't-wash', warn: 't-warn', neutral: 't-neutral', muted: 't-neutral' };
const ovAttr = (sec, item = '', kind = '') => `data-ov="${sec}|${kind}|${item}"`;

function replayCard(d) {
  if (!d.replay) return '';
  const f = d.replay.forward;
  const cell = (lab, v) => `<div>${lab}<b class="${cls(v)}">${v == null ? '—' : pct(v)}</b></div>`;
  return `<div class="card replay">
    <h3>回看 ${d.analysis_date} 當時的分析 <button class="link" id="replay-exit">回到今天</button></h3>
    <p class="tiny" style="margin:0 0 8px">下面所有分析只用到這天以前「已經公布」的資料（營收、財報依公布期限過濾）</p>
    ${f ? `<div class="rets">${cell('之後 5 日', f.d5)}${cell('之後 20 日', f.d20)}${cell('之後 60 日', f.d60)}</div>
      <p class="tiny" style="margin:6px 0 0">之後 ${f.days} 個交易日內：最高 <span class="up">${pct(f.max_up)}</span>、最低 <span class="down">${pct(f.max_down)}</span>（到 ${f.to_date}）</p>` : ''}
  </div>`;
}

function retailCard(d) {
  const r = d.retail;
  if (!r || r.error) return `<div class="card"><h3>散戶退場</h3><p class="warn">${esc(r?.error || '沒有資料')}</p></div>`;
  return `<div class="card">
    <h3>散戶退場<span class="pill ${TONE[r.tone]}">${r.count}/${r.total}</span></h3>
    <p class="muted" style="margin:0 0 6px">${esc(r.summary)}</p>
    <ul class="crit-list retail">${r.signals.map((x, i) => `<li class="${x.exiting ? 'ok' : ''} ${x.date ? 'clickable' : ''}" ${x.date ? ovAttr('retail', i) : ''}>
      <b>${esc(x.label)}</b><span>${esc(x.value)}</span><small>${esc(x.text)}</small></li>`).join('')}</ul>
    <p class="tiny" style="margin:6px 0 0">「退場中」= 散戶正在離開（對長線布局有利）。${esc(r.note)}</p>
  </div>`;
}

function zonesCard(d) {
  const z = d.zones;
  if (!z || z.error) return `<div class="card"><h3>恐慌區間</h3><p class="warn">${esc(z?.error || '沒有資料')}</p></div>`;
  const row = (kind, x, i) => `<tr class="clickable" ${ovAttr('zone', i, kind)}>
      <td>${x.lo === x.hi ? px(x.lo) : `${px(x.lo)}–${px(x.hi)}`}${x.tier ? `<small class="tier t-${x.tier}">${TIER_LABEL[x.tier]}</small>` : ''}</td>
      <td class="${cls(x.dist)}">${x.dist > 0 ? '+' : ''}${x.dist}%</td>
      <td><span class="dots">${'●'.repeat(x.strength)}${'○'.repeat(Math.max(0, 4 - x.strength))}</span></td>
      <td>${kind === 'panic' ? reachTxt(x.reach) : ''}</td>
      <td class="tiny" style="text-align:left;white-space:normal">${esc(x.methods.join('、'))}</td></tr>`;
  return `<div class="card">
    <h3>恐慌區間與壓力<small>點一列畫在圖上</small></h3>
    <p class="muted" style="margin:0 0 8px">${esc(z.summary)}</p>
    <table class="tbl zt"><thead><tr><th>壓力區</th><th>距現價</th><th>重疊</th><th></th><th>依據</th></tr></thead>
      <tbody>${z.resist.slice().reverse().map((x, i, arr) => row('resist', x, arr.length - 1 - i)).join('')}</tbody></table>
    <table class="tbl zt" style="margin-top:8px"><thead><tr><th>恐慌區</th><th>距現價</th><th>重疊</th><th>到達機率</th><th>依據</th></tr></thead>
      <tbody>${z.panic.map((x, i) => row('panic', x, i)).join('')}</tbody></table>
    <p class="tiny" style="margin:6px 0 0">●越多 = 越多種方法指向同一價位。${esc(z.notes.join('；'))}。這是機率區間，不是預言。</p>
  </div>`;
}

function trendCard(d) {
  const r = d.regime;
  if (r.error) return `<div class="card trend"><h3>趨勢狀態</h3><p class="warn">這一塊計算失敗：${esc(r.error)}</p></div>`;
  const catLabel = d.fundamentals.category_info?.label || '一般股';
  const opts = [`<option value="auto">自動（${catLabel} → ${esc(r.profiles[r.auto_profile])}）</option>`]
    .concat(Object.entries(r.profiles).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`)).join('');
  const swingTag = sec => sec.swing ? `<span class="pill ${TONE[sec.swing.tone]}">${esc(sec.swing.label)}</span>` : '';
  return `<div class="card trend">
    <h3>趨勢狀態 <select class="sel" id="profile-sel" aria-label="判斷參數">${opts}</select></h3>
    <div class="state ${TONE[r.tone]}">${esc(r.label)}${r.strength ? `<small>強度：${r.strength}</small>` : ''}</div>
    <p class="muted" style="margin:0">${esc(r.summary || '')}</p>
    ${r.swing ? `<p class="tiny" style="margin:4px 0 0">波段（30% 短線）：<span class="${TONE[r.swing.tone]}">${esc(r.swing.label)}</span>・${esc(r.swing.text)}</p>` : ''}
    <div class="verdicts">${r.sections.filter(sec => sec.verdict).map(sec => `<div class="vd">
      <div class="vh"><b>${esc(sec.name.split(' ')[0])}</b><span class="pill ${TONE[sec.verdict.tone]}">${esc(sec.verdict.label)}</span></div>
      <div class="vt">${esc(sec.verdict.text)}</div>
      <div class="tiny">${esc(sec.what)}</div></div>`).join('')}</div>
    <p class="tiny" style="margin:4px 0 0">${esc(r.profile_label)}：${esc(r.profile_desc)}</p>
    <details class="crit" ${state.critOpen ? 'open' : ''} id="crit"><summary>判斷依據（點標題或條件，圖上會畫出來）</summary>
      <button class="link" id="ov-clear" hidden>清除圖上標記</button>
      ${r.sections.map(sec => `<h4 class="clickable" ${ovAttr(sec.key)}>${esc(sec.name)}<em class="${sec.used ? 'used' : ''}">${sec.used ? '採用' : '參考'}</em>${swingTag(sec)}</h4>
        <ul class="${sec.key === 'minervini' ? 'pass' : 'fav'}">${sec.items.map((it, i) => `<li class="${it.ok === true ? 'ok' : it.ok === false ? 'no' : ''} ${it.draw ? 'clickable' : ''}" ${it.draw ? ovAttr(sec.key, i) : ''}>${esc(it.text)}</li>`).join('')}</ul>`).join('')}
    </details>
  </div>`;
}

const CHK = x => `<li class="${x.ok === true ? 'ok' : x.ok === false ? 'no' : ''}">${esc(x.text)}${x.value ? `<small>${esc(x.value)}</small>` : ''}</li>`;
// 警示型條件（過熱、基本面停損）：成立才是壞事 → 成立顯示橘色「!」，沒成立顯示灰色
const WARN = x => `<li class="${x.ok === true ? 'alarm' : 'calm'}">${esc(x.text)}${x.value ? `<small>${esc(x.value)}</small>` : ''}</li>`;

const reachTxt = r => !r ? '—' : r.pct == null ? '樣本不足' : `${r.pct}%<small class="tiny"> ${r.n}/${r.of}</small>`;
const TIER_LABEL = { normal: '一般回檔', deep: '深度回檔', extreme: '極端恐慌' };

function dangerCard(d) {
  const g = d.danger;
  if (!g || g.error) return `<div class="card"><h3>多頭危機訊號</h3><p class="warn">${esc(g?.error || '沒有資料')}</p></div>`;
  const tone = { healthy: 'bull', watch: 'warn', crisis: 'bear' }[g.level];
  const segs = [['healthy', '健康', '0–1 個', '照計畫布局'], ['watch', '留意', '2–3 個', '不加碼・減 1/3'],
                ['crisis', '危機', '≥4，或 ≥2 且破月線', '再減 1/3・留 1/3']];
  const sig = g.signals.map((x, i) => ({ ...x, i })).sort((p, q) => (q.on ? 1 : 0) - (p.on ? 1 : 0));
  return `<div class="card danger">
    <h3>多頭危機訊號<small>大戶出貨的痕跡，用來決定要不要減碼</small></h3>
    <div class="dmeter">${segs.map(([k, n, c, act]) => `<div class="seg ${k} ${k === g.level ? 'on' : ''}">
      <b>${n}</b><span>${c}</span><em>${act}</em>${k === g.level ? `<i class="here">▲ 目前 ${g.count} 個</i>` : ''}</div>`).join('')}</div>
    <div class="dnow ${TONE[tone]}"><b>${esc(g.label)}</b>　${esc(g.advice)}</div>
    <p class="muted" style="margin:2px 0 8px">${esc(g.summary)}</p>
    ${g.late ? `<p class="hidden-why" style="margin:0 0 8px">${esc(g.late_note)}</p>` : ''}
    <ul class="chk">${sig.map(x => `<li class="${x.on ? 'alarm' : 'calm'} ${x.dates.length ? 'clickable' : ''}" ${x.dates.length ? ovAttr('danger', x.i) : ''}>
      ${esc(x.label)}<span class="dv">${esc(x.value)}</span><small>${esc(x.text)}</small></li>`).join('')}</ul>
    <p class="tiny" style="margin:6px 0 0">亮起來的排在最上面。強勢股常過熱很久還繼續漲，所以分批減碼、不一次賣光。有日期的訊號點一下會標在圖上。</p>
  </div>`;
}

const STATUS_TONE = { '合格': 'bull', '觀察': 'neutral', '論點警訊': 'warn', '循環股': 'muted' };

function coreBox(d) {
  const c = d.longterm?.core || {};
  const ro = d.replay ? 'disabled' : '';
  return `<details class="card core-box" ${state.coreOpen || (c.core && !c.invalidation) ? 'open' : ''} id="core-box">
    <summary><span class="star ${c.core ? 'on' : ''}">${c.core ? '★' : '☆'}</span>${c.core ? '在我的長期名單' : '加入我的長期名單'}
      ${c.core && !c.invalidation ? '<span class="pill t-warn">還沒寫認錯條件</span>' : ''}</summary>
    <form id="core-form" class="core-form">
      <label class="chkline"><input type="checkbox" id="core-on" ${c.core ? 'checked' : ''} ${ro}> 列入長期名單（我認定的長期好股票）</label>
      <label>我看好它的理由<textarea id="core-reason" rows="2" placeholder="例如：AI 伺服器龍頭，營收連年成長，護城河是先進製程" ${ro}>${esc(c.reason || '')}</textarea></label>
      <label>認錯條件（發生就不再加碼、考慮出場）<textarea id="core-inval" rows="2" placeholder="例如：連續 2 季營收年減、毛利率跌破 45%、失去大客戶" ${ro}>${esc(c.invalidation || '')}</textarea></label>
      <button type="submit" ${ro}>儲存</button>
      <p class="tiny" style="margin:0">「長期名單」是你的判斷；下面的體質分數是過去走勢的檢查。兩邊都同意才會給買點。</p>
    </form>
  </details>`;
}

function ladderHtml(d, L) {
  const close = abar(d).close;
  const act = t => t.stage === '恐慌段' ? `跌到 ${px(t.price)} 加碼`
    : t.stage === '回升段' ? (t.hold ? '價位到了，但中期還在出貨，先等' : t.price < close ? `拉回 ${px(t.price)} 附近加碼` : `站回 ${px(t.price)} 加碼`)
    : '大跌才動用備用資金';
  const tag = t => t.stage === '恐慌段' ? '恐慌' + t.n : t.stage === '回升段' ? '回升' + t.n : t.stage;
  const all = [...L.tranches, ...(L.swan || [])].filter(t => t.price);
  const met = all.filter(t => t.met);
  const lad = all.filter(t => !t.met).sort((p, q) => q.price - p.price);
  const cut = lad.findIndex(t => t.price < close);
  const rung = t => `<div class="rung ${t.stage === '恐慌段' ? 'fear' : t.stage === '回升段' ? 'rec' : 'swan'} ${t.hold ? 'hold' : ''}">
      <div class="rp">${px(t.price)}<small class="${cls(t.dist)}">${t.dist == null ? '' : pct(t.dist)}</small></div>
      <div class="rd"><b>${esc(tag(t))}</b>　${esc(act(t))}<small>${esc(t.why || '')}${t.stage !== '回升段' && t.reach ? (t.reach.pct == null || (t.reach.of ?? 0) < 3 ? '・歷史樣本不足，僅供參考' : `・到達機率 ${t.reach.pct}%`) : ''}</small></div></div>`;
  const nowRow = `<div class="rung now"><div class="rp">${px(close)}</div><div class="rd"><b>現價</b>${met.length ? `　<span class="t-bull">✔ ${met.map(tag).join('、')} 可以加碼</span>` : ''}</div></div>`;
  const body = cut < 0 ? lad.map(rung).join('') + nowRow : lad.map((t, i) => (i === cut ? nowRow : '') + rung(t)).join('');
  return `<div class="ladder"><div class="lh"><span>價位（高→低）</span><span>動作</span></div>${body}</div>`;
}

function cyclicalCard(d) {
  const g = d.danger || {}, gTone = { healthy: 'bull', watch: 'warn', crisis: 'bear' }[g.level];
  const pb = d.fundamentals?.valuations?.pbr;
  return `<div class="card plan-top">
    <h3>策略總表<small>${esc(abar(d).date)} 收盤</small></h3>
    <div class="now-do t-muted cyc-box"><span class="lbl">🔄 循環股</span><b>不在這個平台的長線範圍</b>
      <div class="next">循環股的買賣邏輯跟成長股、穩定配息股相反：獲利谷底、本益比看起來很貴時才是買點；獲利高峰、本益比很便宜時反而要小心。
      所以這裡不給長線分批價位，之後用循環股工具（看產品報價、庫存、毛利率方向）判斷。</div></div>
    <div class="why3">
      <div><span>估值參考</span><b class="${TONE[pb?.tone] || ''}">${esc(pb?.zone || '—')}</b><small>PBR 區間（股票體質分頁）</small></div>
      <div><span>中期趨勢</span><b>${esc(d.regime.label || '—')}</b><small>短線波段可參考</small></div>
      <div><span>過熱程度</span><b class="${TONE[gTone] || ''}">${esc(g.label?.replace('多頭', '') || '—')}</b><small>危機訊號 ${g.count ?? '—'}/${g.total ?? '—'}</small></div>
    </div>
    <div class="exit-rules"><h4>如果你已經持有</h4><ul>
      <li class="${['watch', 'crisis'].includes(g.level) ? 'cur' : ''}">過熱「留意」或「危機」→ 停止加碼，持股不動</li>
      <li class="${g.crash?.on ? 'cur' : ''}">股災警報 → 短線 30% 部位減碼，可轉其他商品；長線 70% 不動</li>
      <li>短線波段（30% 資金）照常可用，在下方「詳細分析」</li></ul></div>
    <p class="tiny" style="margin:6px 0 0">分類錯了？到「股票體質」分頁手動改分類，手動的優先於自動判斷。</p>
  </div>`;
}

function planCard(d) {
  const L = d.strategy.long, LT = d.longterm || {};
  if (!L) return `<div class="card"><h3>策略總表</h3><p class="warn">${esc(d.strategy.error || '無法計算')}</p></div>`;
  if ((L.eligibility || LT.elig || {}).cyclical) return cyclicalCard(d);
  const el = L.eligibility || LT.elig || {}, tq = LT.tech, ft = LT.fund, r = d.regime, g = d.danger || {};
  const dec = L.decision || { headline: L.action, tone: L.tone, next: [] };
  const usedSec = (r.sections || []).filter(x => x.verdict && x.used).pop() || (r.sections || []).find(x => x.verdict);
  const mid = usedSec?.verdict;
  const gTone = { healthy: 'bull', watch: 'warn', crisis: 'bear' }[g.level];
  const core = LT.core || {};
  const T = L.target;
  return `<div class="card plan-top">
    <h3>策略總表<small>${esc(abar(d).date)} 收盤・長線 70%</small></h3>
    <div class="now-do ${TONE[dec.tone] || ''}"><span class="lbl">現在</span><b>${esc(dec.headline)}</b>
      ${L.tranches.length && dec.next?.length ? `<div class="next">下一步：${dec.next.map(esc).join('　／　')}</div>` : ''}</div>
    <div class="why3">
      <div><span>長期體質</span><b class="${TONE[STATUS_TONE[el.status]] || ''}">${esc(el.status || '—')}</b>
        <small>${tq ? `技術 ${tq.passed}/${tq.total}` : ''}${ft ? `・基本面 ${ft.passed}/${ft.total}` : el.etf ? '・ETF' : ''}</small></div>
      <div><span>中期趨勢</span><b class="${TONE[mid?.tone] || ''}">${esc(mid?.label || r.label || '—')}</b>
        <small>${esc(r.label || '')}${usedSec ? '・' + esc(usedSec.name.split(' ')[0]) : ''}</small></div>
      <div><span>過熱程度</span><b class="${g.late ? 't-neutral' : TONE[gTone] || ''}">${g.late ? '已跌深' : esc(g.label?.replace('多頭', '') || '—')}</b>
        <small>${g.late ? `從高點回檔 ${g.drawdown}%，訊號過期` : `危機訊號 ${g.count ?? '—'}/${g.total ?? '—'}`}</small></div>
    </div>
    ${el.warns?.length ? `<ul class="warns">${el.warns.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
    ${L.tranches.length ? `
      ${T ? `<div class="target"><span class="lbl">恐慌目標區</span><b>${px(T.lo)}${T.hi - T.lo > T.hi * 0.003 ? '–' + px(T.hi) : ''}</b>
        <span class="${cls(T.dist)}">${pct(T.dist)}</span><span class="tiny">到達機率 ${reachTxt(T.reach)}${T.low_prob ? '・<b class="t-warn">機率偏低</b>' : ''}${!T.reach || T.reach.pct == null || (T.reach.of ?? 0) < 3 ? '・<b class="t-warn">歷史樣本不足，這個價位僅供參考</b>' : ''}</span>
        <div class="tiny">「到得了」的最深一層（距現價 ≤30%、過去到達機率 ≥30%）；再往下的是黑天鵝價位，大跌才動用備用資金</div></div>` : ''}
      ${ladderHtml(d, L)}
      <p class="tiny" style="margin:6px 0 0">恐慌＝跌到才買，越低買越多（退可守）；回升＝還沒到目標就反轉時跟上（進可攻）。</p>`
      : `<p class="hidden-why">${L.hidden_reason && L.hidden_reason !== dec.headline ? '不列出買點：' + esc(L.hidden_reason) : '所以不列出買點。確認理由還成立、體質回到「觀察」或「合格」後再看。'}</p>`}
    <div class="exit-rules"><h4>持股原則：長線只增不減</h4><ul>
      <li class="${['watch', 'crisis'].includes(g.level) && !g.late ? 'cur' : ''}">過熱「留意」「危機」，或高檔轉弱 → 停止加碼，持股不動</li>
      <li class="${g.crash?.on ? 'cur' : ''}">股災警報（大盤過熱危機、大盤跌破年線且年線下彎、或這檔體質轉壞）→ 短線 30% 部位減碼，資金可轉其他商品；長線 70% 不動
        ${g.crash?.on ? `<div class="tiny t-bear">現在：${g.crash.reasons.map(esc).join('；')}</div>` : ''}</li>
      <li>認錯條件：${core.invalidation ? `<b>${esc(core.invalidation)}</b>` : '<span class="t-warn">還沒寫，到下面「我的長期名單」填</span>'}（成立時重新評估這檔）</li>
      <li>長線不設價格停損</li></ul></div>
  </div>`;
}

function qualityCard(d) {
  const L = d.strategy.long, LT = d.longterm || {};
  if (!L) return '';
  const el = L.eligibility || LT.elig || {}, tq = LT.tech, ft = LT.fund;
  return `<div class="card"><div class="chk-grid">
      <div><h4>技術面長期體質${tq ? `<small> 近 ${tq.years} 年</small>` : ''}</h4>
        ${tq ? `<ul class="chk">${tq.items.map(CHK).join('')}</ul>` : '<p class="tiny">資料不足</p>'}</div>
      <div><h4>基本面趨勢</h4>
        ${ft ? `<ul class="chk">${ft.items.map(CHK).join('')}</ul>${ft.warns?.length ? `<ul class="chk">${ft.warns.map(w => `<li class="alarm">${esc(w)}</li>`).join('')}</ul>` : ''}`
             : `<p class="tiny">${el.etf ? 'ETF 是一籃子股票，不做個股基本面' : '沒有資料'}</p>`}</div>
      <div><h4>加分：恐慌／便宜</h4><ul class="chk">${L.fear.map(CHK).join('')}</ul></div>
    </div>
    <p class="tiny" style="margin:6px 0 0">合格 = 技術體質至少 ${tq ? Math.max(3, tq.total - 2) : 4} 項＋基本面至少 2 項（ETF 只看技術）。散戶退場、估值便宜是加分，不是門檻。</p></div>`;
}

const fold = (key, title, sum, html) => `<details class="fold" data-k="${key}" ${state.folds?.[key] ? 'open' : ''}>
  <summary><b>${title}</b><span>${sum}</span></summary>${html}</details>`;

function exitCard(d) {
  const g = d.danger || {}, z = d.zones || {}, P = d.portfolio || {}, close = abar(d).close;
  if (g.error) return `<div class="card"><h3>過熱與股災</h3><p class="warn">${esc(g.error)}</p></div>`;
  const M = g.market, C = g.crash || {};
  const held = P.has_position ? P.shares : 0;
  const hot = ['watch', 'crisis'].includes(g.level) && !g.late;
  const rs = (z.resist || []).slice(0, 3);
  const mk = M ? `<div class="why3 mkt">
      <div><span>大盤過熱（0050）</span><b class="${M.warn ? 't-bear' : M.heat === 'watch' && !M.heat_late ? 't-warn' : 't-bull'}">${esc(M.heat_late ? '已跌深' : (M.heat_label || '—').replace('多頭', ''))}</b><small>危機訊號 ${M.count ?? '—'}/${M.total ?? '—'}</small></div>
      <div><span>大盤年線</span><b class="${M.bear ? 't-bear' : M.close < M.ma240 ? 't-warn' : 't-bull'}">${M.bear ? '空頭確認' : M.close < M.ma240 ? '跌破、年線未下彎' : '在年線上'}</b><small>0050 ${px(M.close)}・年線 ${px(M.ma240)}${M.ma240_down ? ' ↘' : ' ↗'}</small></div>
      <div><span>這檔過熱</span><b class="${hot ? 't-warn' : 't-bull'}">${g.late ? '已跌深' : esc((g.label || '—').replace('多頭', ''))}</b><small>危機訊號 ${g.count ?? '—'}/${g.total ?? '—'}</small></div>
    </div>` : '<p class="tiny">大盤（0050）資料不足，股災警報只看這檔體質</p>';
  return `<div class="card exit-card">
    <h3>過熱與股災<small>長線只增不減，只有股災警報才減短線部位</small></h3>
    <div class="dnow ${C.on ? 't-bear' : hot ? 't-warn' : 't-bull'}"><b>${C.on ? '股災警報' : hot ? (g.cooling ? '高檔轉弱：停止加碼' : '過熱：停止加碼') : '正常'}</b>　${C.on ? esc(C.advice) : hot ? (g.cooling ? '頂部訊號還亮著、股價已經往下走：持股不動，等跌到恐慌價位，或重新站穩月線再加碼' : '持股不動，等降溫或回檔再照計畫加碼') : '持股照常抱，照長線計畫的價位加碼'}</div>
    ${C.on ? `<ul class="warns">${C.reasons.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${held ? `<p class="tiny" style="margin:2px 0 8px">你持有 ${lots(held)}，均價 ${px(P.avg_cost)}，目前 ${pct(P.unrealized_pct)}${C.on ? `；短線 30% 約 <b>${lots(Math.max(1, Math.round(held * 0.3)))}</b>` : ''}</p>` : ''}
    ${mk}
    <h4>什麼時候出現股災警報</h4>
    <ul class="exit-list">
      <li class="${M?.warn ? 'cur' : ''}">大盤（0050）過熱「危機」：股災預告，在高檔先降低短線部位</li>
      <li class="${M?.bear ? 'cur' : ''}">大盤（0050）跌破年線，而且年線往下彎：空頭確認</li>
      <li class="${d.longterm?.elig?.status === '論點警訊' ? 'cur' : ''}">這檔長期體質轉壞（論點警訊）</li>
    </ul>
    <h4>上方壓力區<small>股災警報時，短線部位可以在這裡減碼</small></h4>
    ${rs.length ? `<table class="tbl"><thead><tr><th>壓力價</th><th>距現價</th><th>重疊</th><th>依據</th></tr></thead><tbody>
      ${rs.map(x => `<tr><td>${px(x.lo)}${x.hi - x.lo > x.hi * 0.003 ? '–' + px(x.hi) : ''}</td><td class="${cls(x.dist)}">${pct(x.dist)}</td>
        <td><span class="dots">${'●'.repeat(x.strength)}${'○'.repeat(Math.max(0, 4 - x.strength))}</span></td><td class="tiny">${esc((x.methods || []).join('、'))}</td></tr>`).join('')}
      </tbody></table>` : '<p class="tiny">上方沒有明顯壓力（在歷史高點附近）</p>'}
    <p class="tiny" style="margin:6px 0 0">過熱只代表「別再追」，不代表要賣：強勢股常常過熱很久還繼續漲。真正要防的是整個市場轉空頭，這時候把短線部位換成債券 ETF 或現金，長線部位留著等下一輪。</p>
  </div>`;
}

// ---------- 長線回測 ----------
function lbtCard(d) {
  const r = state.lbt?.[d.stock_id], all = state.lbtAll, y = state.lbtY || 3;
  const seg = `<div class="seg lbt-y">${[1, 2, 3, 5].map(k => `<button data-lbty="${k}" class="${k === y ? 'on' : ''}">近 ${k} 年</button>`).join('')}</div>`;
  const money = v => v == null ? '—' : (v / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 1 }) + ' 萬';
  const row = (lab, a) => !a || !a.n ? `<tr><td>${lab}</td><td colspan="7" class="tiny">這段期間沒有買點</td></tr>`
    : `<tr><td>${lab}</td><td>${a.n}</td><td class="${a.success >= 50 ? 't-bull' : 't-bear'}"><b>${a.success}%</b></td>
      <td class="b50"><span class="${cls(a.avg)}">${pct(a.avg)}</span><small class="tiny">最差 ${pct(a.worst)}</small></td>
      <td class="b50">${a.cagr == null ? '<small class="tiny">未滿半年</small>' : `<span class="${cls(a.cagr)}">${pct(a.cagr)}</span>`}<small class="tiny">平均抱 ${Math.round(a.hold / 21)} 個月</small></td>
      <td class="b50">${a.f6 == null ? '<small class="tiny">未滿半年</small>' : `<span class="${cls(a.f6)}">${pct(a.f6)}</span><small class="tiny">${a.f6_n} 筆，${a.f6_win}% 賺</small>`}</td>
      ${b50(a)}<td class="tiny">${money(a.invested)} → <b class="${cls(a.profit)}">${money(a.value)}</b>${a.bench_value != null ? `<br>0050：${money(a.bench_value)}` : ''}</td></tr>`;
  // 同一天、同金額改買 0050：0050 的平均報酬，加上個股贏了幾次
  const b50 = a => a.bench_avg == null ? '<td>—</td>' : `<td class="b50"><span class="${cls(a.bench_avg)}">${pct(a.bench_avg)}</span><small class="tiny ${a.beat_n * 2 >= a.bench_n ? 't-bull' : 't-bear'}">個股贏 ${a.beat_n}/${a.bench_n} 次</small></td>`;
  const dcaRow = (c, a) => !c?.n ? '' : `<tr class="dca"><td>0050<br><small class="tiny">每月無腦買</small></td><td>${c.n}</td><td colspan="6" class="tiny">每個月買的次數和個股一樣，在月初第一個交易日開盤買。總報酬 <b class="${cls(c.total)}">${pct(c.total)}</b>${a?.n ? `，個股 ${pct(a.total)}：<b class="${a.total > c.total ? 't-bull' : 't-bear'}">${a.total > c.total ? '個股贏' : '0050 贏'}</b>` : ''}</td><td class="tiny">${money(c.invested)} → <b class="${cls(c.value - c.invested)}">${money(c.value)}</b></td></tr>`;
  const head = `<thead><tr><th></th><th>買幾次</th><th>現在賺錢</th><th>到今天<br><small class="tiny">平均</small></th><th>年化</th><th>買後半年<br><small class="tiny">平均</small></th><th>同一天買 0050<br><small class="tiny">到今天平均</small></th><th>投入 → 現值</th></tr></thead>`;
  let one = '';
  if (r?.error) one = `<p class="warn">${esc(r.error)}</p>`;
  else if (r) {
    const W = r.summary[y], ts = (r.trades[y] || []).slice().reverse();
    one = `${r.cyclical ? '<p class="hidden-why">這檔是循環股，策略總表平常不給買點；下面只是照同樣規則算給你參考</p>' : ''}<p class="tiny">${esc(d.name)}・${esc(W.from)} 到 ${esc(r.last)}，照每天的策略總表，碰到買點就買 5 萬，全部抱到今天（收盤 ${px(r.close)}${r.has_divs ? '，含領到的股利' : ''}）${W.short ? '・<b class="t-warn">歷史資料不到這麼久，從有資料的那天開始</b>' : ''}</p>
    <div class="lbt-wrap"><table class="tbl bt">${head}<tbody>${row('全部', W.all)}${row('回升段', W.up)}${row('恐慌段', W.down)}${dcaRow(W.dca, W.all)}</tbody></table></div>
    ${ts.length ? `<button class="btn-s lbt-mark ${state.overlay?.sec === 'lbt' && state.overlay.kind === String(y) ? 'on' : ''}" ${ovAttr('lbt', '', String(y))}>${state.overlay?.sec === 'lbt' && state.overlay.kind === String(y) ? '✕ 收起 K 線上的買點' : '📍 詳細資料：在 K 線上標出買點'}</button>
    <details class="lbt-list" open><summary class="tiny">每一筆（最近的在上面）</summary>
      <div><table class="tbl"><thead><tr><th>買進日</th><th>買點</th><th>買價</th><th>到今天</th><th>買後半年</th><th>同期 0050</th></tr></thead><tbody>
      ${ts.map(t => `<tr><td>${esc(t.date)}</td><td title="${esc(t.why)}">${esc(t.label)}</td><td>${px(t.price)}</td>
        <td class="${cls(t.ret)}">${pct(t.ret)}</td><td class="${cls(t.f6)}">${t.f6 != null ? pct(t.f6) : '<small class="tiny">未滿</small>'}</td><td class="${cls(t.bench)}">${t.bench != null ? pct(t.bench) : '—'}</td></tr>`).join('')}
      </tbody></table></div></details>` : ''}`;
  }
  const many = all ? `<p class="tiny" style="margin-top:12px">全部自選股・近 ${y} 年照策略總表買，抱到今天${all.skipped?.length ? `（循環股、ETF 不算：${all.skipped.map(esc).join('、')}）` : ''}</p>
    <table class="tbl bt"><thead><tr><th>股票</th><th>買幾次</th><th>現在賺錢</th><th>平均</th><th>同一天買 0050<br><small class="tiny">平均</small></th><th>投入 → 現值</th></tr></thead><tbody>
      ${all.stocks.map(s => { const a = s.summary[y]; return `<tr><td>${esc(s.name)}<small class="tiny"> ${esc(s.stock_id)}</small></td>${a.n ? `<td>${a.n}</td><td class="${a.success >= 50 ? 't-bull' : 't-bear'}">${a.success}%</td><td class="${cls(a.avg)}">${pct(a.avg)}</td>${b50(a)}<td class="tiny">${money(a.invested)} → <b class="${cls(a.profit)}">${money(a.value)}</b></td>` : '<td colspan="5" class="tiny">沒有買點</td>'}</tr>`; }).join('')}
      ${(() => { const a = all.total[y].all, c = all.total[y].dca; return a.n ? `<tr class="tot"><td><b>合計</b></td><td>${a.n}</td><td><b>${a.success}%</b></td><td class="${cls(a.avg)}">${pct(a.avg)}</td>${b50(a)}<td class="tiny">${money(a.invested)} → <b class="${cls(a.profit)}">${money(a.value)}</b><br>總報酬 ${pct(a.total)}${a.bench_value != null ? `<br>0050：${money(a.bench_value)}` : ''}</td></tr>`
        + (c?.n ? `<tr class="dca"><td>0050<br><small class="tiny">每月無腦買</small></td><td>${c.n}</td><td colspan="3" class="tiny">同樣的次數、月初買 0050：<b class="${a.total > c.total ? 't-bull' : 't-bear'}">${a.total > c.total ? '個股策略贏' : '0050 贏'}</b></td><td class="tiny">${money(c.invested)} → <b class="${cls(c.value - c.invested)}">${money(c.value)}</b><br>總報酬 ${pct(c.total)}</td></tr>` : '') : ''; })()}
    </tbody></table>` : '';
  const bd = (r && !r.error ? r.bench_divs : all?.bench_divs);
  return `<div class="card">
    <h3>長線回測<small>照策略總表的買點，每次 5 萬，抱到今天</small></h3>
    <div class="bt-btns"><button class="btn-s" id="lbt-one">這檔</button><button class="btn-s" id="lbt-all">全部自選股</button>${seg}</div>
    ${one}${many}
    <p class="tiny" style="margin:8px 0 0">程式從近 N 年的第一天開始，一天一天往後走：每天收盤後只用「當天以前」的資料，重算一次策略總表（恐慌區、壓力、恐慌 1／2／3、回升 1／2、趨勢、過熱），隔天照表操作——試單和已到價的開盤買，其他恐慌價位掛限價、碰到就買；回升段顯示「可以加碼」才買；過熱時停止加碼；黑天鵝是備用資金不算。同一種買點買過後，要創新高或過半年、且隔 20 個交易日以上才會再買。報酬 = 抱到今天、假設今天賣（含股利，扣手續費和稅）。同一天碰到好幾個買點只買一次。比較回升段和恐慌段請看「年化」和「買後半年」：越早買的抱越久，「到今天」天生比較高。第一次算一檔約 2～3 秒，全部自選股約 1 分鐘，之後只算新的交易日。</p>
    <p class="tiny" style="margin:4px 0 0">要注意：①自選股多半是「已經漲上來」才被選進來的，回測結果會偏好（倖存者偏差）；②長期體質、估值分類用的是現在的判斷，當時的財報沒有重算；③${bd === false ? '<b class="t-warn">0050 還沒有配息資料，「贏 0050」會偏向個股；按一次「全部更新」或點開 0050 會補抓</b>' : '0050 也含息比較'}。</p>
  </div>`;
}

function renderTech() {
  const d = state.data, a = d.analysis, s = d.strategy;
  const close = abar(d).close, date = abar(d).date;
  const rel = v => v == null ? '' : `<small>${pct((v / close - 1) * 100)}</small>`;
  const pos = Math.max(0, Math.min(100, 50 + a.score * 50 / 6));
  const vc = a.verdict === '偏多' ? 'v-bull' : a.verdict === '偏空' ? 'v-bear' : 'v-neutral';
  const rt = a.returns;
  const g = d.danger || {}, z = d.zones || {}, rr = d.retail || {}, LT = d.longterm || {};
  const pn = (z.panic || [])[0], rsx = (z.resist || [])[0];
  const techSig = `<div class="card">
    <div class="verdict ${vc}">
      <div class="row"><strong>${a.verdict}</strong><span class="sub">${esc(a.trend)} · 訊號分數 ${a.score > 0 ? '+' : ''}${a.score}</span></div>
      <div class="meter" title="訊號分數 −6 ～ +6"><i style="left:${pos}%"></i></div>
    </div>
    <div class="rets">
      <div>5 日<b class="${cls(rt.d5)}">${pct(rt.d5)}</b></div>
      <div>20 日<b class="${cls(rt.d20)}">${pct(rt.d20)}</b></div>
      <div>60 日<b class="${cls(rt.d60)}">${pct(rt.d60)}</b></div>
    </div>
    <ul class="sig">${a.signals.map(x => `<li><b>${esc(x.label)}</b><span>${esc(x.text)}</span><i class="${x.tone}"></i></li>`).join('')}</ul>
    <div class="levels">
      <span>支撐<b>${px(a.levels.support)}</b></span><span>月線<b>${px(a.levels.ma20)}</b></span>
      <span>季線<b>${px(a.levels.ma60)}</b></span><span>壓力<b>${px(a.levels.resistance)}</b></span><span>ATR<b>${px(s.swing?.atr)}</b></span>
    </div></div>`;
  const tq = LT.tech, ft = LT.fund;
  const hot = ['watch', 'crisis'].includes(g.level) && !g.late;
  const lb = state.lbt?.[d.stock_id], ly = state.lbtY || 3, lba = lb && !lb.error ? lb.summary[ly].all : null;
  $('tab-tech').innerHTML = replayCard(d) + planCard(d) + coreBox(d) +
    fold('lbt', '長線回測（每次 5 萬）', lba?.n ? `近 ${ly} 年照表買 ${lba.n} 次・現在賺錢 <b>${lba.success}%</b>・${(lba.invested / 10000).toLocaleString('zh-TW')} 萬 → ${(lba.value / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 1 })} 萬` : '點開，看近 1／2／3／5 年照這套買到今天的結果', lbtCard(d)) +
    `<div class="fold-title">詳細分析<span class="tiny">點開看依據；點裡面的條件，圖上會畫出來</span></div>` +
    fold('trend', '趨勢判斷（三種方法）', esc(d.regime.label || ''), trendCard(d)) +
    fold('danger', '多頭危機訊號（減碼用）', `${esc(g.label || '—')}・${g.count ?? '—'}/${g.total ?? '—'}`, dangerCard(d)) +
    fold('zones', '恐慌區間與壓力', `${pn ? '恐慌 ' + px(pn.mid) + '（' + pct(pn.dist) + '）' : ''}${rsx ? '・壓力 ' + px(rsx.lo) : ''}`, zonesCard(d)) +
    fold('retail', '散戶退場', `${rr.count ?? '—'}/${rr.total ?? '—'}`, retailCard(d)) +
    fold('quality', '長期體質明細', `${tq ? '技術 ' + tq.passed + '/' + tq.total : ''}${ft ? '・基本面 ' + ft.passed + '/' + ft.total : ''}`, qualityCard(d)) +
    fold('signal', '技術訊號（短期）', `${esc(a.verdict)}・${esc(date)}`, techSig) +
    fold('exit', '過熱與股災', `${g.crash?.on ? '<b class="t-bear">股災警報：短線部位減碼</b>' : g.late ? '跌深了，持股照常抱' : hot ? '<b class="t-warn">' + esc(g.label) + '，停止加碼</b>' : '正常，持股照常抱'}${g.market ? `・大盤${g.market.bear ? '<b class="t-bear">空頭</b>' : g.market.warn ? '<b class="t-bear">過熱危機</b>' : '正常'}` : ''}`, exitCard(d));
  if ($('profile-sel')) $('profile-sel').value = d.settings.trend_profile;
  const crit = $('crit'); if (crit) crit.addEventListener('toggle', () => { state.critOpen = crit.open; });
}

// ---------- 股票體質 tab ----------
function valuationCard(v, close, primary) {
  if (!v) return '';
  if (v.unfit && !primary) return `<details class="card unfit"><summary><h3>${esc(v.name)}<span class="pill t-neutral">不適用這檔</span></h3>
    <p class="tiny" style="margin:4px 0 0">${esc(v.unfit)}（點開看數字）</p></summary>${valuationBody(v, close)}</details>`;
  if (v.unavailable) return `<div class="card"><h3>${esc(v.name)}</h3><p class="muted" style="margin:0">${esc(v.unavailable)}</p></div>`;
  return `<div class="card">
    <h3>${esc(v.name)}${primary ? '<small>主要估值</small>' : ''}${v.draft ? '<span class="tag">邏輯待補充</span>' : ''}</h3>${valuationBody(v, close)}</div>`;
}

function valuationBody(v, close) {
  const prices = v.bands.map(b => b.price);
  const lo = Math.min(prices[0] * 0.8, close * 0.95), hi = Math.max(prices[2] * 1.15, close * 1.05);
  const at = x => ((x - lo) / (hi - lo) * 100).toFixed(1);
  const extra = b => b.rate ? `殖利率 ${+(b.rate * 100).toFixed(2)}%${b.note ? `<small class="tiny"> ${esc(b.note)}</small>` : b.pct_rank != null ? `<small class="tiny"> 歷史第 ${b.pct_rank} 百分位</small>` : ''}` : b.peg != null ? `PEG ${b.peg}<small class="tiny"> = ${b.per} 倍</small>` : b.pbr != null ? `PBR ${b.pbr}` : b.per != null ? `PER ${b.per}` : '';
  return `
    <div class="zone ${TONE[v.tone]}">${esc(v.zone)}</div>
    <div class="scale" aria-hidden="true"><div class="bar"></div>
      ${prices.map(p => `<i class="tickm" style="left:${at(p)}%"></i>`).join('')}
      <span class="now" style="left:${at(close)}%">現價 ${px(close)}</span></div>
    <table class="tbl"><thead><tr><th></th><th>價格</th><th>依據</th><th>距現價</th></tr></thead><tbody>
      ${v.bands.map(b => `<tr><td>${esc(b.label)}</td><td>${px(b.price)}</td><td>${extra(b)}</td><td class="${cls(b.price - close)}">${pct((b.price / close - 1) * 100)}</td></tr>`).join('')}
    </tbody></table>
    <p class="tiny" style="margin:8px 0 0">${esc(v.formula)}</p>
    ${v.trend_note ? `<p class="hidden-why" style="margin:8px 0 0">${esc(v.trend_note)}</p>` : ''}`;
}

function etfDivCard(f) {
  const E = f.etf_div;
  if (!E) return `<div class="card"><h3>配息</h3><p class="tiny">${f.etf_div_error ? '配息計算失敗：' + esc(f.etf_div_error) : '還沒有配息資料：按一次「全部更新」或重新點開這檔，會補抓'}</p></div>`;
  const ev = E.events.slice().reverse();
  return `<div class="card">
    <h3>配息<small>${esc(E.freq)}</small></h3>
    <div class="why3">
      <div><span>近 12 個月殖利率</span><b class="t-bull">${E.ttm_yield != null ? E.ttm_yield + '%' : '—'}</b><small>配 ${E.ttm_n} 次，合計 ${fmt(E.ttm_cash)} 元</small></div>
      <div><span>近 ${E.avg5_n} 年平均年殖利率</span><b>${E.avg5 != null ? E.avg5 + '%' : '—'}</b><small>每年各次殖利率加總的平均</small></div>
      <div><span>最近一次</span><b>${fmt(ev[0].cash)} 元</b><small>${esc(ev[0].ex)} 除息・當次 ${ev[0].yield ?? '—'}%</small></div>
    </div>
    <table class="tbl" style="margin-top:8px"><thead><tr><th>年度</th><th>配息次數</th><th>合計配息</th><th>年殖利率</th></tr></thead><tbody>
      ${E.years.slice().reverse().map(y => `<tr><td>${y.year}</td><td>${y.n}</td><td>${fmt(y.cash)}</td><td>${y.yield}%</td></tr>`).join('')}
    </tbody></table>
    <details class="lbt-list"><summary class="tiny">每一次配息（最近的在上面）</summary>
      <div><table class="tbl"><thead><tr><th>除息日</th><th>配息</th><th>除息前價格</th><th>當次殖利率</th></tr></thead><tbody>
      ${ev.map(e => `<tr><td>${esc(e.ex)}</td><td>${fmt(e.cash)}</td><td>${e.price != null ? px(e.price) : '—'}</td><td>${e.yield != null ? e.yield + '%' : '—'}</td></tr>`).join('')}
      </tbody></table></div></details>
    ${E.split_note ? `<p class="tiny" style="margin:6px 0 0">${esc(E.split_note)}</p>` : ''}
    <p class="tiny" style="margin:4px 0 0">年殖利率 = 當年每一次「配息 ÷ 除息前一天收盤」加總。ETF 配息來自成分股股利和收益平準金，金額每次都可能變。</p>
  </div>`;
}

function renderFund() {
  const d = state.data, f = d.fundamentals, close = abar(d).close;
  if (f.error) {
    $('tab-fund').innerHTML = `<div class="card"><h3>股票體質</h3><p class="warn">這一塊計算失敗：${esc(f.error)}</p>
      <p class="tiny">可能是 FinMind 的資料格式和預期不同，請把這段訊息截圖給 Claude。</p></div>`;
    return;
  }
  if (f.etf) {
    $('tab-fund').innerHTML = `<div class="card"><div class="cat-head"><span class="ic">🧺</span><div><strong>ETF</strong>
      <div class="tiny">一籃子股票，不做個股基本面（營收、EPS、估值）分析</div></div></div>
      <p class="tiny" style="margin:6px 0 0">ETF 的長期判斷看「技術」分頁的長期體質（站上年線時間、年線方向、對 0050 的相對表現）和多頭危機訊號。</p></div>
      ${etfDivCard(f)}`;
    return;
  }
  const cl = f.classification, info = f.category_info;
  const catOpts = [`<option value="auto">自動判斷（${f.categories[cl.auto].label}）</option>`]
    .concat(Object.entries(f.categories).map(([k, v]) => `<option value="${k}">${v.icon} ${v.label}</option>`)).join('');
  const sec = cl.secondary.map(k => `${f.categories[k].icon} ${f.categories[k].label}：${(cl.secondary_reasons[k] || []).join('；')}`);
  const rev = f.revenue, eps = f.eps, dv = f.dividends;
  const maxRev = rev ? Math.max(...rev.annual.map(a => a.revenue)) : 1;
  const pegWith = f.primary_method === 'per';
  const others = Object.entries(f.valuations).filter(([k]) => k !== f.primary_method && !(pegWith && k === 'peg'));
  $('tab-fund').innerHTML = `
    <div class="card">
      <div class="cat-head"><span class="ic">${info.icon}</span><div><strong>${info.label}</strong>
        <div class="tiny">${f.manual ? '手動設定' : '自動判斷'} · 估值用 ${esc(f.valuations[f.primary_method]?.name || info.method)}${f.primary_method === 'per' ? '＋PEG' : ''}</div></div></div>
      <ul class="reasons">${(f.manual ? ['你手動設定的分類'] : cl.reasons).map(x => `<li>${esc(x)}</li>`).join('')}
        ${sec.map(x => `<li class="tiny">也符合 ${esc(x)}</li>`).join('')}</ul>
      <label class="tiny">分類錯了？手動改：<select class="sel" id="cat-sel">${catOpts}</select></label>
    </div>

    ${f.corp_actions ? `<p class="${f.corp_actions.status === 'ok' ? 'corp-ok' : 'hidden-why'}">${f.corp_actions.status === 'ok' ? '🔁 ' : '⚠️ '}${esc(f.corp_actions.note)}</p>` : ''}
    ${f.primary_note ? `<p class="hidden-why">${esc(f.primary_note)}</p>` : ''}
    ${f.valuation_combo ? `<div class="combo ${TONE[f.valuation_combo.tone] || ''}"><b>本益比＋PEG 一起看</b><div>${esc(f.valuation_combo.text)}</div></div>` : ''}
    ${valuationCard(f.valuations[f.primary_method], close, true)}
    ${pegWith ? valuationCard(f.valuations.peg, close, true) : ''}

    <div class="card"><h3>EPS 預估<small>${eps ? eps.year + ' 年' : ''}</small></h3>
      ${eps ? `<table class="tbl"><thead><tr><th></th>${eps.quarters.map(q => `<th>Q${q.q}</th>`).join('')}</tr></thead><tbody>
        <tr><td>今年</td>${eps.quarters.map(q => `<td>${q.eps == null ? '<span class="tiny">推估</span>' : fmt(q.eps)}</td>`).join('')}</tr>
        <tr><td>去年</td>${eps.quarters.map(q => `<td>${fmt(q.prev)}</td>`).join('')}</tr></tbody></table>
        <dl class="kv" style="margin-top:8px"><dt>全年預估 EPS</dt><dd><b style="font-size:18px">${fmt(eps.estimate)}</b></dd>
        <dt>推估方式</dt><dd>${esc(eps.method)}</dd></dl>
        <p class="tiny" style="margin:6px 0 0">${esc(eps.note)}</p>` : '<p class="muted">沒有 EPS 資料</p>'}
    </div>

    <div class="card"><h3>營收成長
      ${rev ? (rev.passed_rule == null ? '<span class="pass na">資料不足（需要 4 個完整年度）</span>'
        : `<span class="pass ${rev.passed_rule ? 'ok' : 'no'}">${rev.passed_rule ? '符合' : '不符合'}</span>`) : ''}</h3>
      ${rev ? `<label class="tiny">長線體質用的營收規則：<select class="sel" id="rev-rule">
        <option value="strict">嚴格：三年每年都成長</option><option value="lenient">寬鬆：三年整體成長，容許一年 ≤5% 衰退</option><option value="trend">趨勢：可以有衰退年，但要回到高點、現在沒在衰退</option></select></label>
        ${rev.rule === 'trend' && rev.trend_why ? `<p class="tiny" style="margin:4px 0 0">${esc(rev.trend_why)}</p>` : ''}` : ''}
      ${rev ? `<div class="revbars">${rev.annual.map(a => `<div><b class="${cls(a.yoy)}">${a.yoy == null ? '' : pct(a.yoy)}</b>
          <i style="height:${Math.max(4, a.revenue / maxRev * 60)}px"></i>${a.year}</div>`).join('')}</div>
        <dl class="kv"><dt>今年 1–${rev.ytd.month} 月累計年增</dt><dd class="${cls(rev.ytd.yoy)}">${pct(rev.ytd.yoy)}</dd>
        <dt>近 12 個月年增</dt><dd class="${cls(rev.ttm_yoy)}">${pct(rev.ttm_yoy)}</dd>
        <dt>近 3 年年複合成長</dt><dd>${pct(rev.cagr3)}</dd></dl>` : '<p class="muted">沒有營收資料</p>'}
    </div>

    <div class="card"><h3>股利<small>連續 ${dv.streak} 年配息${f.dividend_yield ? ` · 殖利率 ${f.dividend_yield}%` : ''}</small></h3>
      ${dv.history.length ? `<table class="tbl"><thead><tr><th>盈餘年度</th><th>EPS</th><th>現金股利</th><th>配息率</th><th>除息價</th><th>當時殖利率</th></tr></thead><tbody>
        ${dv.history.slice().reverse().map(h => `<tr><td>${h.year}</td><td>${fmt(h.eps)}</td><td>${fmt(h.cash)}</td><td>${h.payout == null ? '—' : h.payout + '%'}</td>
          <td title="${esc((h.ex_dates || []).join('、'))}">${h.ex_price == null ? '<span class="tiny">尚未除息</span>' : fmt(h.ex_price) + (h.ex_n > 1 ? `<small class="tiny"> ${h.ex_n} 次平均</small>` : '')}</td>
          <td>${h.ex_yield == null ? '—' : h.ex_yield + '%' + (h.ex_done ? '' : '<small class="tiny"> 未完</small>')}</td></tr>`).join('')}
        </tbody></table>
        <p class="tiny" style="margin:6px 0 0">除息價 = 除息前一天收盤價${f.corp_actions?.events?.length ? '（除權／分割以前的已換算成現在股數，和 K 線圖對得上）' : '（就是當時真正的價格）'}；當時殖利率 = 每次配息 ÷ 當時股價，全年加總。「未完」= 這年度的配息還沒全部發完（例如季配股才配了 1 季），殖利率會偏低。</p><p class="tiny" style="margin:6px 0 0">${dv.med_payout != null ? `近 ${dv.n_payout} 年配息率中位數 <b>${dv.med_payout}%</b>（估值用這個，不會被單一年度拉偏）・` : ''}近 3 年平均 ${dv.avg_payout ?? '—'}%</p>` : '<p class="muted">沒有配息紀錄</p>'}
    </div>

    <details class="crit"><summary>其他估值參考</summary><div style="margin-top:10px">
      ${others.map(([, v]) => valuationCard(v, close, false)).join('')}</div></details>`;
  $('cat-sel').value = d.settings.category;
  if ($('rev-rule')) $('rev-rule').value = d.prefs?.rev_rule || 'strict';
}

// ---------- 我的持股 tab ----------
function renderHold() {
  const d = state.data, p = d.portfolio, close = abar(d).close;
  const form = `<form class="card trade-form" id="trade-form" autocomplete="off">
      <h3 style="margin:0">記錄交易</h3>
      <div class="side-seg" id="side-seg"><button type="button" data-side="buy">買進</button><button type="button" data-side="sell">賣出</button></div>
      <div class="row">
        <label>日期<input type="date" id="t-date" value="${abar(d).date}" max="${today()}" required></label>
        <label>成交價<input type="number" id="t-price" step="0.01" min="0.01" value="${close}" required inputmode="decimal"></label>
      </div>
      <label>數量<span class="qty"><input type="number" id="t-qty" min="1" step="1" value="1" required inputmode="numeric">
        <select id="t-unit"><option value="lot">張</option><option value="share">股</option></select></span></label>
      <button class="submit" type="submit">記錄</button>
      <p class="form-msg" id="t-msg" hidden></p>
    </form>`;
  let body = '';
  if (p.error) body += `<div class="warn">${esc(p.error)}，請刪除有問題的紀錄</div>`;
  const csv = `<p class="tiny" style="margin:4px 0 0"><a href="/api/trades.csv" download style="color:var(--accent)">匯出全部交易紀錄（CSV）</a> · 資料庫每天自動備份到 data\\backup</p>`;
  if (p.has_position) {
    const c = cls(p.unrealized);
    body += `<div class="card"><h3>目前持股<small>${esc(p.fee_note)}</small></h3>
      <div class="pos-grid">
        <div class="big">未實現淨損益（現價賣出）<b class="${c}">${money(p.unrealized)} 元 <small>${pct(p.unrealized_pct)}</small></b></div>
        <div>持有<b>${sharesTxt(p.shares)}</b></div>
        <div>平均成本<b>${fmt(p.avg_cost)}</b></div>
        <div>損益兩平價<b style="color:var(--cost)">${px(p.breakeven)}</b></div>
        <div>總成本<b>${Math.round(p.total_cost).toLocaleString('zh-TW')}</b></div>
      </div>
      ${p.hint ? `<div class="hint ${p.hint.tone}">${esc(p.hint.text)}</div>` : ''}
    </div>
    <div class="card"><h3>賣在各價位<small>已扣手續費、證交稅</small></h3>
      <table class="tbl"><thead><tr><th>情境</th><th>價格</th><th>距現價</th><th>淨損益</th><th>報酬</th></tr></thead><tbody>
      ${p.scenarios.slice().reverse().map(x => `<tr class="${x.kind === 'now' ? 'hl' : x.kind === 'breakeven' ? 'be' : ''}">
        <td>${esc(x.label)}</td><td>${px(x.price)}</td><td>${x.kind === 'now' ? '—' : pct(x.dist)}</td>
        <td class="${cls(x.net)}">${money(x.net)}</td><td class="${cls(x.pct)}">${pct(x.pct)}</td></tr>`).join('')}
      </tbody></table></div>`;
  } else if (!p.error) {
    body += `<p class="muted" style="margin:4px 0 12px">目前沒有持股。記錄買進後，這裡會算平均成本、損益兩平價，以及賣在停損、壓力、目標價的淨損益。</p>`;
  }
  if (p.trades.length) {
    body += `<div class="card"><h3>交易紀錄<small>已實現損益 <span class="${cls(p.realized)}">${money(p.realized)}</span> 元</small></h3>
      <ul class="hist">${p.trades.map(t => `<li>
        <span>${t.date}</span><span class="s-${t.side}">${t.side === 'buy' ? '買' : '賣'}</span>
        <span>${sharesTxt(t.shares)} @ ${px(t.price)}<small>費 ${t.fee ?? '—'}${t.tax ? ` · 稅 ${t.tax}` : ''}</small></span>
        <span class="${cls(t.pnl)}">${t.pnl != null ? money(t.pnl) : ''}</span>
        <button class="del" data-del="${t.id}" title="刪除" aria-label="刪除這筆">×</button></li>`).join('')}</ul></div>`;
  }
  const pf = d.prefs || {};
  $('tab-hold').innerHTML = (d.replay ? `<p class="warn">回看模式：顯示 ${d.analysis_date} 當時的持股狀況，不能新增交易</p>` : '') + form + body + csv;
  if (d.replay) $('trade-form').querySelectorAll('input,select,button').forEach(x => { x.disabled = true; });
  $('t-unit').value = state.unit;
  syncSide();
}

function syncSide() {
  document.querySelectorAll('#side-seg button').forEach(b => b.classList.toggle('on', b.dataset.side === state.side));
}

function renderTabs() {
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === state.tab));
  document.querySelectorAll('.tabpane').forEach(p => { p.hidden = p.dataset.pane !== state.tab; });
}

function renderPanels() {
  for (const [fn, el] of [[renderTech, 'tab-tech'], [renderFund, 'tab-fund'], [renderHold, 'tab-hold']]) {
    try { fn(); } catch (e) { console.error(e); $(el).innerHTML = `<p class="warn">畫面顯示失敗：${esc(e.message)}</p>`; }
  }
  renderTabs();
  const d = state.data, r = d.regime, ci = d.fundamentals.category_info;
  const rb = $('regime-badge'), cb = $('cat-badge'), lb = $('long-badge'), el = d.longterm?.elig;
  rb.hidden = !!r.error;
  if (!r.error) { rb.className = 'badge ' + TONE[r.tone]; rb.textContent = '中期：' + r.label + (r.strength ? '・' + r.strength : ''); }
  lb.hidden = !el;
  if (el) { lb.className = 'badge ' + (TONE[STATUS_TONE[el.status]] || ''); lb.textContent = (el.core ? '★ ' : '') + '長期：' + el.status; lb.title = el.warns?.join('；') || ''; }
  cb.hidden = !ci;
  if (ci) cb.textContent = `${ci.icon} ${ci.label}`;
}

// ---------- watchlist ----------
function spark(vals, c) {
  if (!vals || vals.length < 2) return '';
  const lo = Math.min(...vals), hi = Math.max(...vals), w = 64, h = 26;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 2 - (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * (h - 4)).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--${c === 'up' ? 'up' : c === 'down' ? 'down' : 'flat'})" stroke-width="1.4"/></svg>`;
}

function renderWatchlist() {
  $('watchlist').innerHTML = state.list.map(q => {
    const c = cls(q.change);
    const right = state.confirmRm === q.stock_id
      ? `<span class="err">還有持股，再按 × 移除（紀錄會保留）</span>`
      : q.error
      ? `<span class="err">${esc(q.error)}</span>`
      : `${spark(q.spark, c)}<div class="px num">${px(q.close)}<small class="${c}">${pct(q.change_pct)}</small></div>`;
    return `<li data-id="${esc(q.stock_id)}" class="${q.stock_id === state.current ? 'active' : ''}" tabindex="0">
      <div class="nm"><b>${q.core ? '<span class="cstar" title="我的長期名單">★</span>' : ''}${q.cyclical ? '<span class="cyc" title="循環股：不適用這個平台的長線規則">🔄</span>' : ''}${esc(q.name)}${q.held ? '<span class="held">持</span>' : ''}${q.crash ? `<span class="crash" title="${esc(q.crash.join('；'))}：短線 30% 部位減碼">股災</span>` : ''}${q.buy ? `<span class="swing" title="${q.buy.trial ? '短期下跌中，長線計畫可以先試單' : `已到長線計畫恐慌段第 ${q.buy.n} 批價位 ${q.buy.p}`}">${q.buy.trial ? '可試單' : '到買點'}</span>` : ''}${!q.crash && (q.heat === 'watch' || q.heat === 'crisis') ? `<span class="hot" title="${q.cooling ? '持股高檔轉弱：停止加碼，持股不動' : '持股過熱：停止加碼，持股不動'}">${q.cooling ? '轉弱' : '過熱'}</span>` : ''}</b><span>${esc(q.stock_id)}</span></div>
      ${right}
      <button class="rm" data-rm="${esc(q.stock_id)}" title="移除" aria-label="移除 ${esc(q.name)}">×</button></li>`;
  }).join('') || '<p class="empty">還沒有自選股，從上面加入</p>';
}

async function loadWatchlist(quiet = false) {
  if (!quiet) $('watchlist').innerHTML = '<p class="empty">讀取中…</p>';
  let r;
  try { r = await api('/api/watchlist'); }
  catch (e) { $('watchlist').innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  state.list = r.quotes; renderWatchlist();
  showAlerts(r.alerts);
}

// ---------- select stock ----------
let loadCtl = null;
async function select(id, force = false) {
  if (state.current && state.current !== id && state.asOf) state.asOf = null;   // 換股票：回到今天
  state.current = id; store.set('current', id);
  renderWatchlist();
  if (loadCtl) loadCtl.abort();  // 快速切換時取消上一檔
  if (state.data && state.data.stock_id !== id) state.overlay = null;
  const ctl = loadCtl = new AbortController();
  const msg = $('chart-msg');
  if (!state.data || force || state.data.stock_id !== id) { msg.textContent = '載入中…'; msg.hidden = !!state.data && !force; }
  $('refresh').classList.add('spin');
  try {
    const qs = new URLSearchParams();
    if (force) qs.set('force', 'true');
    if (state.asOf) qs.set('as_of', state.asOf);
    const d = await api(`/api/stock/${encodeURIComponent(id)}${qs.toString() ? '?' + qs : ''}`, { signal: ctl.signal });
    if (state.current !== id) return;
    state.data = d;
    const last = abar(d), prev = d.bars[aIdx(d) - 1] || last, chg = last.close - prev.close;
    $('sym-name').textContent = d.name;
    $('sym-id').textContent = d.stock_id;
    $('sym-ind').textContent = d.industry || '';
    $('px').textContent = px(last.close);
    $('px').className = cls(chg);
    $('chg').className = cls(chg);
    $('chg').textContent = `${chg > 0 ? '▲' : chg < 0 ? '▼' : ''} ${fmt(Math.abs(chg))}（${pct(chg / prev.close * 100)}）`;
    document.title = `${d.name} ${px(last.close)} · 我的看盤台`;
    await ensureTfBars(id, state.tf);
    if (state.current !== id) return;
    msg.hidden = true;
    drawChart();
    renderPanels();
    drawOverlay(false);
    $('asof').value = d.replay ? d.analysis_date : today();
    $('replay-badge').hidden = !d.replay;
    if (d.replay) $('replay-badge').textContent = `回看 ${d.analysis_date}`;
    const w = $('warn');
    w.hidden = !d.warning;
    w.textContent = d.warning ? `無法更新，顯示的是快取資料：${d.warning}` : '';
    renderStatus();
    const q = state.list.find(x => x.stock_id === id);
    if (!d.replay && q && (q.date !== last.date || q.missing)) loadWatchlist(true);  // 這檔有新資料，同步清單
  } catch (e) {
    if (e.name === 'AbortError' || state.current !== id) return;
    if (state.asOf) { toast(e.message); state.asOf = null; return; }
    msg.textContent = `讀不到 ${id}：${e.message}`; msg.hidden = false;
  } finally {
    if (loadCtl === ctl) $('refresh').classList.remove('spin');
  }
}

// ---------- status ----------
let status = null;
const WD = '日一二三四五六';
function renderStatus() {
  if (!status) return;
  const el = $('status');
  const exp = status.expected_date, wd = WD[new Date(exp + 'T00:00:00').getDay()];
  const stale = state.list.filter(q => q.stale || q.missing).length;
  const fresh = stale ? `<span class="at"> · ${stale} 檔未到 ${exp.slice(5)} 收盤</span>`
                      : `<span class="at"> · 皆為 ${exp.slice(5)}（週${wd}）收盤</span>`;
  el.classList.toggle('demo', status.mode === 'demo');
  el.classList.toggle('stale', !!stale);
  el.innerHTML = (status.mode === 'demo'
    ? '<i class="dot"></i>示範資料（非真實行情）'
    : `<i class="dot"></i>FinMind 日K${status.token ? '' : '（未設 token）'}`) + fresh;
}

function toast(text, ms = 3500) {
  const t = $('toast'); t.textContent = text; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}

async function refreshAll(force) {
  const btn = $('refresh-all');
  btn.disabled = true; btn.classList.add('busy');
  try {
    const r = await api('/api/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force }),
    });
    state.list = r.quotes; renderWatchlist(); renderStatus();
    if (force || r.updated.length) {
      const parts = [];
      if (r.updated.length) parts.push(`更新 ${r.updated.length} 檔`);
      if (r.latest) parts.push(`${r.latest} 檔已是最新`);
      if (r.fetched && !r.updated.length && !r.failed.length) parts.push('交易所還沒有新的收盤資料');
      if (r.failed.length) parts.push(`${r.failed.length} 檔失敗：${r.failed[0].error}`);
      toast(parts.join('，'));
    }
    showAlerts(r.alerts);  // 通知比較重要，放最後才不會被蓋掉
    if (state.current && (r.updated.includes(state.current) || force)) select(state.current, force);
    setTimeout(() => loadWatchlist(true), 60000);   // 後台補算長線計畫後，再更新一次清單標籤和通知
  } catch (e) {
    toast('更新失敗：' + e.message);
  } finally {
    btn.disabled = false; btn.classList.remove('busy');
  }
}

// ---------- events ----------
function syncButtons() {
  document.querySelectorAll('#tfs button').forEach(b => b.classList.toggle('on', b.dataset.tf === state.tf));
  document.querySelectorAll('#ranges button').forEach(b => b.classList.toggle('on', +b.dataset.n === state.range));
  document.querySelectorAll('#subs button').forEach(b => b.classList.toggle('on', b.dataset.sub === state.sub));
  document.querySelectorAll('#mas button').forEach(b => b.classList.toggle('on', !!state.mas[b.dataset.ma]));
}

$('ranges').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.range = +b.dataset.n; store.set('range', state.range); syncButtons(); applyRange();
});
$('subs').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.sub = b.dataset.sub; store.set('sub', state.sub); syncButtons(); drawSub();
});
$('tfs').addEventListener('click', e => {
  const b = e.target.closest('button[data-tf]'); if (!b) return;
  setTF(b.dataset.tf);
});
$('mas').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  const k = b.dataset.ma; state.mas[k] = !state.mas[k]; store.set('mas', state.mas); syncButtons();
  if (k === 'plan' || k === 'cost') drawPlan(); else syncSeriesVisibility();
  updateLegend();
});
$('refresh').addEventListener('click', () => state.current && select(state.current, true));
$('refresh-all').addEventListener('click', () => refreshAll(true));

$('watchlist').addEventListener('click', async e => {
  const rm = e.target.closest('[data-rm]');
  if (rm) {
    e.stopPropagation();
    const id = rm.dataset.rm, q = state.list.find(x => x.stock_id === id);
    if (q?.held && state.confirmRm !== id) {  // 有持股：先提醒，再按一次才移除
      state.confirmRm = id; renderWatchlist(); return;
    }
    state.confirmRm = null;
    const idx = state.list.findIndex(x => x.stock_id === id);
    state.list = state.list.filter(x => x.stock_id !== id);  // 先從畫面移除
    renderWatchlist(); renderStatus();
    if (id === state.current && state.list.length) select(state.list[Math.min(idx, state.list.length - 1)].stock_id);
    api(`/api/watchlist/${encodeURIComponent(id)}`, { method: 'DELETE' })
      .catch(err => { toast('移除失敗：' + err.message); loadWatchlist(true); });
    return;
  }
  if (state.confirmRm) { state.confirmRm = null; renderWatchlist(); }
  const li = e.target.closest('li[data-id]');
  if (li && li.dataset.id !== state.current) select(li.dataset.id);
});
$('watchlist').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const li = e.target.closest('li[data-id]'); if (li) select(li.dataset.id);
});

let sugTimer;
$('add-input').addEventListener('input', e => {
  clearTimeout(sugTimer);
  const q = e.target.value.trim();
  if (!q) return;
  sugTimer = setTimeout(async () => {
    try {
      const rows = await api('/api/search?q=' + encodeURIComponent(q));
      $('sugg').innerHTML = rows.map(r => `<option value="${esc(r.stock_id)}">${esc(r.name)} · ${esc(r.industry || '')}</option>`).join('');
    } catch {}
  }, 200);
});
$('add-form').addEventListener('submit', async e => {
  e.preventDefault();
  const input = $('add-input'), msg = $('add-msg');
  const id = input.value.trim().split(/\s/)[0];
  if (!id) return;
  msg.hidden = false; msg.textContent = `加入 ${id} 中…`;
  try {
    const q = await api('/api/watchlist', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stock_id: id }),
    });
    if (!state.list.some(x => x.stock_id === q.stock_id)) state.list.push(q);
    input.value = ''; msg.hidden = true;
    select(q.stock_id);
  } catch (err) {
    msg.textContent = err.message;
  }
});

// ---------- 波段通知 ----------
function showAlerts(alerts) {
  if (!alerts || !alerts.length) return;
  toast(alerts.map(a => a.title).join('；'), 8000);
  if (state.notify && 'Notification' in window && Notification.permission === 'granted') {
    for (const a of alerts) {
      try { new Notification(a.title, { body: `${a.text}（${a.date} 收盤）` }); } catch {}
    }
  }
}

function syncBell() {
  const b = $('bell');
  const on = state.notify && 'Notification' in window && Notification.permission === 'granted';
  b.classList.toggle('on', on);
  b.title = on ? '股價跌到恐慌段買點、持股過熱時會跳出桌面通知（再按關閉）' : '開啟桌面通知';
}

$('bell').addEventListener('click', async () => {
  if (!('Notification' in window)) { toast('這個瀏覽器不支援桌面通知'); return; }
  if (state.notify) { state.notify = false; store.set('notify', false); syncBell(); toast('已關閉桌面通知'); return; }
  const perm = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
  state.notify = perm === 'granted'; store.set('notify', state.notify); syncBell();
  toast(state.notify ? '已開啟：自選股跌到恐慌段買點、持股過熱時會通知（平台開著時）' : '瀏覽器沒有允許通知');
});

// ---------- 回看日期 ----------
function setAsOf(v) {
  state.asOf = v || null;
  if (state.current) select(state.current);
}
$('asof').max = today();
$('asof-go').addEventListener('click', () => { if ($('asof').value) setAsOf($('asof').value); });
$('asof').addEventListener('keydown', e => { if (e.key === 'Enter' && $('asof').value) setAsOf($('asof').value); });
$('replay-badge').addEventListener('click', () => setAsOf(null));

// ---------- 每張卡片都可以收起來（點標題或箭頭）----------
const closedCards = new Set(store.get('closedCards', []));
const cardKey = h => (h.childNodes[0]?.textContent || h.textContent).trim().slice(0, 24);
function makeCollapsible(root) {
  root.querySelectorAll('.card').forEach(c => {
    if (c.closest('details.fold') || c.tagName === 'DETAILS') return;    // 已經在摺疊區裡的不重複
    const h = [...c.children].find(x => x.tagName === 'H3');
    if (!h || h.classList.contains('ct')) return;
    h.classList.add('ct');
    h.insertAdjacentHTML('afterbegin', '<span class="carr" aria-hidden="true"></span>');
    c.dataset.ck = cardKey(h) || '';
    c.classList.toggle('closed', closedCards.has(c.dataset.ck));
  });
}
document.querySelector('.analysis').addEventListener('click', e => {
  const h = e.target.closest('h3.ct');
  if (!h || e.target.closest('select, input, button, a, label, textarea')) return;
  const c = h.parentElement, k = c.dataset.ck;
  c.classList.toggle('closed');
  c.classList.contains('closed') ? closedCards.add(k) : closedCards.delete(k);
  store.set('closedCards', [...closedCards]);
});
for (const id of ['tab-tech', 'tab-fund', 'tab-hold']) {
  new MutationObserver(() => makeCollapsible($(id))).observe($(id), { childList: true });
}

// ---------- 右側欄寬度：拖曳中間的分隔線 ----------
(() => {
  const root = document.documentElement, sp = $('splitter');
  const clamp = w => Math.max(320, Math.min(w, window.innerWidth - 420));
  const apply = w => root.style.setProperty('--side-w', clamp(w) + 'px');
  const saved = store.get('sideW', null);
  if (saved) apply(saved);
  let drag = false;
  sp.addEventListener('pointerdown', e => { drag = true; sp.setPointerCapture(e.pointerId); document.body.classList.add('resizing'); });
  sp.addEventListener('pointermove', e => { if (drag) apply(window.innerWidth - e.clientX); });
  const end = e => {
    if (!drag) return;
    drag = false; document.body.classList.remove('resizing');
    store.set('sideW', parseInt(getComputedStyle(root).getPropertyValue('--side-w')) || 400);
  };
  sp.addEventListener('pointerup', end); sp.addEventListener('pointercancel', end);
  sp.addEventListener('dblclick', () => { root.style.removeProperty('--side-w'); store.set('sideW', null); });
  window.addEventListener('resize', () => { const w = store.get('sideW', null); if (w) apply(w); });
})();

// 右側分頁
$('tabs').addEventListener('click', e => {
  const b = e.target.closest('button[data-tab]'); if (!b) return;
  state.tab = b.dataset.tab; store.set('tab', state.tab); renderTabs();
});

async function saveSettings(body) {
  try {
    await api(`/api/settings/${encodeURIComponent(state.current)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch (e) { $('warn').hidden = false; $('warn').textContent = e.message; return; }
  select(state.current);
}

document.querySelector('.analysis').addEventListener('change', e => {
  if (e.target.id === 'profile-sel') saveSettings({ trend_profile: e.target.value });
  if (e.target.id === 'cat-sel') saveSettings({ category: e.target.value });
  if (e.target.id === 'rev-rule') {
    api('/api/prefs', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rev_rule: e.target.value }) })
      .then(() => { toast('營收規則已更新，所有股票都會套用'); select(state.current); })
      .catch(err => toast(err.message));
  }
  if (e.target.id === 't-unit') { state.unit = e.target.value; store.set('unit', state.unit); }
});

document.querySelector('.analysis').addEventListener('click', async e => {
  if (e.target.id === 'replay-exit') { setAsOf(null); return; }
  if (e.target.id === 'lbt-one' || e.target.id === 'lbt-all') {
    const one = e.target.id === 'lbt-one', btn = e.target;
    btn.disabled = true; btn.textContent = '計算中…';
    try {
      if (one) { state.lbt = state.lbt || {}; state.lbt[state.current] = await api(`/api/longbt/${encodeURIComponent(state.current)}`); }
      else state.lbtAll = await api('/api/longbt');
    } catch (err) { toast('回測失敗：' + err.message); }
    renderTech(); drawOverlay(false);
    return;
  }
  const lby = e.target.closest('[data-lbty]');
  if (lby) {
    state.lbtY = +lby.dataset.lbty; store.set('lbtY', state.lbtY);
    if (state.overlay?.sec === 'lbt') state.overlay = { ...state.overlay, kind: String(state.lbtY) };
    renderTech(); drawOverlay(false); return;
  }
  if (e.target.id === 'ov-clear') { state.overlay = null; drawOverlay(false); return; }
  const ov = e.target.closest('[data-ov]');
  if (ov) {
    const [sec, kind, item] = ov.dataset.ov.split('|');
    toggleOverlay({ sec, kind: kind || undefined, item: item === '' ? null : +item });
    return;
  }
  const sb = e.target.closest('#side-seg button');
  if (sb) { state.side = sb.dataset.side; syncSide(); return; }
  const del = e.target.closest('[data-del]');
  if (del) {
    try { await api(`/api/trades/${del.dataset.del}`, { method: 'DELETE' }); } catch {}
    await select(state.current); loadWatchlist(true);
  }
});

document.querySelector('.analysis').addEventListener('submit', async e => {
  if (e.target.id === 'core-form') {
    e.preventDefault();
    const body = { core: $('core-on').checked, reason: $('core-reason').value.trim(), invalidation: $('core-inval').value.trim() };
    try {
      await api(`/api/core/${encodeURIComponent(state.current)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      state.coreOpen = false;
      toast(body.core ? '已存入長期名單' : '已移出長期名單');
      await select(state.current); loadWatchlist(true);
    } catch (err) { toast(err.message); }
    return;
  }
  if (e.target.id !== 'trade-form') return;
  e.preventDefault();
  const msg = $('t-msg');
  const qty = parseInt($('t-qty').value, 10);
  const shares = state.unit === 'lot' ? qty * 1000 : qty;
  const body = { stock_id: state.current, date: $('t-date').value, side: state.side,
                 price: parseFloat($('t-price').value), shares };
  if (!body.date || !(body.price > 0) || !(shares > 0)) { msg.hidden = false; msg.textContent = '日期、價格、數量都要填'; return; }
  try {
    await api('/api/trades', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch (err) { msg.hidden = false; msg.textContent = err.message; return; }
  await select(state.current); loadWatchlist(true);
});

document.querySelector('.analysis').addEventListener('toggle', e => {
  if (e.target.classList?.contains('fold')) { state.folds = state.folds || {}; state.folds[e.target.dataset.k] = e.target.open; }
  if (e.target.id === 'core-box') state.coreOpen = e.target.open;
}, true);

new ResizeObserver(() => setPaneHeights()).observe($('chart'));

// ---------- boot ----------
(async () => {
  initChart();
  syncButtons();
  syncBell();
  try { status = await api('/api/status'); } catch {}
  await loadWatchlist();          // 先顯示資料庫裡的資料，不連網路
  renderStatus();
  const saved = store.get('current', null);
  const first = state.list.find(q => q.stock_id === saved && !q.missing) || state.list.find(q => !q.missing);
  if (first) await select(first.stock_id);
  // 開 app 自動更新：只更新「還沒有最新收盤、且超過 30 分鐘沒抓」的股票
  if (state.list.some(q => q.stale || q.missing)) await refreshAll(false);
  if (!state.current && state.list.find(q => !q.missing)) select(state.list.find(q => !q.missing).stock_id);
  else if (!state.list.length) $('chart-msg').textContent = '還沒有自選股，從右下角加入';
})();
}
