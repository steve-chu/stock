// 股票新增中繼站（Cloudflare Worker + 一個 Durable Object 存全部狀態）
//
// 手機：
//   POST /add {id}            排進佇列（已經算好、而且是今天的就直接回 ready）
//   GET  /status?ids=a,b      每檔的狀態：pending／running／ready／error
//   GET  /file/<路徑>          算好的檔案（stock/2603.json、quote/2603.json…）
// GitHub 上的計算機器（要帶 X-Key）：
//   POST /claim               領走所有排隊中的工作（同時表示「我還活著」）
//   POST /put?path=…          上傳一個結果檔（gzip）
//   POST /done {id, ok, error} 回報一檔完成或失敗
// 每天的建置：
//   GET  /extra               大家新增過的所有股票代號（每天一起更新）
//
// 派工規則：有工作排隊、而且目前沒有機器在跑 → 叫 GitHub 開一台；
// 機器跑的時候又有新增 → 它會繼續領，不會再開第二台。

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Key',
  'Access-Control-Max-Age': '86400',
};
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json', ...CORS } });

export default {
  async fetch(req, env) {
    if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });
    const stub = env.RELAY.get(env.RELAY.idFromName('main'));
    return stub.fetch(req);
  },
};

const ID_RE = /^[0-9A-Z]{4,6}$/;
const BUSY_MS = 90_000;        // 機器多久沒消息就當作已經關機
const BOOT_MS = 150_000;       // 叫 GitHub 開機後，給它多久時間開起來
const FRESH_MS = 20 * 3600_000; // 算好的結果多久內算「今天的」

export class Relay {
  constructor(state, env) {
    this.s = state.storage;
    this.env = env;
  }

  async fetch(req) {
    const url = new URL(req.url), p = url.pathname, now = Date.now();
    try {
      if (p === '/add' && req.method === 'POST') return this.add(await req.json(), now);
      if (p === '/status') return this.status((url.searchParams.get('ids') || '').split(',').filter(Boolean), now);
      if (p.startsWith('/file/')) return this.file(p.slice(6));
      if (p === '/extra') return json({ ids: (await this.s.get('extra')) || [] });
      if (p === '/') return json({ ok: true, name: 'stock-relay' });
      // 以下只有計算機器能用
      if (req.headers.get('X-Key') !== this.env.RUNNER_KEY) return json({ error: 'forbidden' }, 403);
      if (p === '/claim' && req.method === 'POST') return this.claim(now);
      if (p === '/put' && req.method === 'POST') return this.put(url.searchParams.get('path'), await req.arrayBuffer());
      if (p === '/done' && req.method === 'POST') return this.done(await req.json(), now);
      return json({ error: 'not found' }, 404);
    } catch (e) {
      return json({ error: String(e && e.message || e) }, 500);
    }
  }

  async jobs() { return (await this.s.get('jobs')) || {}; }

  async add(body, now) {
    const id = String(body.id || '').trim().toUpperCase();
    if (!ID_RE.test(id)) return json({ error: '股票代號格式不對' }, 400);
    const jobs = await this.jobs(), j = jobs[id];
    const extra = (await this.s.get('extra')) || [];
    if (!extra.includes(id)) { extra.push(id); await this.s.put('extra', extra); }
    if (j && j.status === 'ready' && now - j.at < FRESH_MS) return json({ id, status: 'ready' });
    if (!j || j.status === 'ready' || j.status === 'error') {
      jobs[id] = { status: 'pending', at: now };
      await this.s.put('jobs', jobs);
    }
    await this.kick(now);
    return json({ id, status: jobs[id].status });
  }

  // 有排隊、沒有機器在跑 → 叫 GitHub 開一台
  async kick(now) {
    const jobs = await this.jobs();
    // 機器關掉時還沒做完的，放回排隊
    const busy = ((await this.s.get('busyUntil')) || 0) > now;
    let changed = false;
    for (const [id, j] of Object.entries(jobs)) {
      if (j.status === 'running' && !busy) { j.status = 'pending'; changed = true; }
    }
    if (changed) await this.s.put('jobs', jobs);
    const waiting = Object.values(jobs).some(j => j.status === 'pending');
    if (!waiting || busy) return;
    await this.s.put('busyUntil', now + BOOT_MS);   // 先標記，避免兩個新增同時叫出兩台機器
    const r = await fetch(`https://api.github.com/repos/${this.env.GH_REPO}/actions/workflows/${this.env.WORKFLOW}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.env.GH_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'stock-relay', 'X-GitHub-Api-Version': '2022-11-28' },
      body: JSON.stringify({ ref: 'main' }),
    });
    if (r.status !== 204) {
      await this.s.put('busyUntil', 0);
      await this.s.put('lastKickError', `${r.status} ${(await r.text()).slice(0, 200)}`);
    }
  }

  async status(ids, now) {
    await this.kick(now);   // 順便自我修復：上次叫不起來、或機器中途掛了，就再叫一次
    const jobs = await this.jobs(), out = {};
    for (const id of ids) out[id] = jobs[id] || { status: 'none' };
    return json({ jobs: out, busy: ((await this.s.get('busyUntil')) || 0) > now, kickError: await this.s.get('lastKickError') || null });
  }

  async claim(now) {
    const jobs = await this.jobs(), ids = [];
    for (const [id, j] of Object.entries(jobs)) if (j.status === 'pending') { j.status = 'running'; j.at = now; ids.push(id); }
    await this.s.put('jobs', jobs);
    await this.s.put('busyUntil', now + BUSY_MS);
    await this.s.delete('lastKickError');
    return json({ ids });
  }

  async put(path, buf) {
    if (!path || !/^[\w./-]+\.json$/.test(path) || path.includes('..')) return json({ error: 'bad path' }, 400);
    if (buf.byteLength > 1_900_000) return json({ error: 'too big' }, 413);
    await this.s.put('f:' + path, buf);
    return json({ ok: true });
  }

  async done(body, now) {
    const jobs = await this.jobs(), id = String(body.id || '').toUpperCase();
    if (!jobs[id]) jobs[id] = {};
    jobs[id] = body.ok ? { status: 'ready', at: now } : { status: 'error', at: now, error: String(body.error || '失敗').slice(0, 200) };
    if (!body.ok) {   // 失敗的（例如代號不存在）不要每天一直算
      const extra = ((await this.s.get('extra')) || []).filter(x => x !== id);
      await this.s.put('extra', extra);
    }
    await this.s.put('jobs', jobs);
    await this.s.put('busyUntil', now + BUSY_MS);
    return json({ ok: true });
  }

  async file(path) {
    const buf = await this.s.get('f:' + path);
    if (!buf) return json({ error: 'not found' }, 404);
    return new Response(buf, {
      encodeBody: 'manual',
      headers: { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip', 'Cache-Control': 'no-store', ...CORS },
    });
  }
}
