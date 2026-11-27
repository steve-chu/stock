// 中繼站的單元測試：不連 Cloudflare、不連 GitHub，用假的儲存空間和假的 fetch 跑真正的程式。
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { gzipSync, gunzipSync } from 'node:zlib';
import worker, { Relay } from '../src/index.js';

const KEY = 'k';
let relay, dispatches, ghStatus, clock;

class Storage {
  constructor() { this.m = new Map(); }
  async get(k) { return this.m.get(k); }
  async put(k, v) { this.m.set(k, v); }
  async delete(k) { this.m.delete(k); }
}

beforeEach(() => {
  dispatches = 0; ghStatus = 204; clock = 1_800_000_000_000;
  Date.now = () => clock;
  globalThis.fetch = async (url, opt) => {
    assert.match(String(url), /api\.github\.com\/repos\/me\/stock\/actions\/workflows\/ondemand\.yml\/dispatches/);
    assert.equal(opt.headers.Authorization, 'Bearer gh');
    dispatches++;
    return new Response(ghStatus === 204 ? null : 'nope', { status: ghStatus });
  };
  relay = new Relay({ storage: new Storage() }, { RUNNER_KEY: KEY, GH_TOKEN: 'gh', GH_REPO: 'me/stock', WORKFLOW: 'ondemand.yml' });
});

const req = (method, path, body, key) => new Request('https://relay.test' + path, {
  method, body: body === undefined ? undefined : (body instanceof Uint8Array ? body : JSON.stringify(body)),
  headers: { 'Content-Type': 'application/json', ...(key ? { 'X-Key': key } : {}) },
});
const call = async (...a) => { const r = await relay.fetch(req(...a)); return { status: r.status, body: r.headers.get('Content-Encoding') === 'gzip' ? r : await r.json() }; };

test('新增：排隊並叫 GitHub 開機器', async () => {
  const r = await call('POST', '/add', { id: '2603' });
  assert.equal(r.body.status, 'pending');
  assert.equal(dispatches, 1);
});

test('同時兩檔新增只開一台機器', async () => {
  await call('POST', '/add', { id: '2603' });
  await call('POST', '/add', { id: '2382' });
  await call('POST', '/add', { id: '2603' });   // 重複按
  assert.equal(dispatches, 1);
  const c = await call('POST', '/claim', undefined, KEY);
  assert.deepEqual(c.body.ids.sort(), ['2382', '2603']);
});

test('機器跑的時候又新增：不再開第二台，下一次領工作會領到', async () => {
  await call('POST', '/add', { id: '2603' });
  await call('POST', '/claim', undefined, KEY);
  clock += 20_000;
  await call('POST', '/add', { id: '3231' });
  assert.equal(dispatches, 1);
  const c = await call('POST', '/claim', undefined, KEY);
  assert.deepEqual(c.body.ids, ['3231']);
});

test('機器關機後再新增：會再開一台；做到一半的放回排隊', async () => {
  await call('POST', '/add', { id: '2603' });
  await call('POST', '/claim', undefined, KEY);
  clock += 200_000;   // 機器早就沒消息了
  const s = await call('GET', '/status?ids=2603');
  assert.equal(s.body.jobs['2603'].status, 'pending');
  assert.equal(dispatches, 2);
});

test('叫不起 GitHub 時記下錯誤，下次查狀態會再試', async () => {
  ghStatus = 401;
  await call('POST', '/add', { id: '2603' });
  let s = await call('GET', '/status?ids=2603');
  assert.match(s.body.kickError, /^401/);
  ghStatus = 204;
  s = await call('GET', '/status?ids=2603');
  assert.equal(s.body.busy, true);
  assert.ok(dispatches >= 3);
});

test('只有機器（帶通關密語）能領工作、上傳、回報', async () => {
  assert.equal((await call('POST', '/claim')).status, 403);
  assert.equal((await call('POST', '/claim', undefined, 'wrong')).status, 403);
  assert.equal((await call('POST', '/done', { id: '2603', ok: true })).status, 403);
});

test('上傳結果、手機讀得到（gzip）', async () => {
  const data = { stock_id: '2603', bars: [1, 2, 3] };
  const put = await relay.fetch(new Request('https://relay.test/put?path=stock/2603.json', { method: 'POST', body: gzipSync(JSON.stringify(data)), headers: { 'X-Key': KEY } }));
  assert.equal(put.status, 200);
  const r = await relay.fetch(req('GET', '/file/stock/2603.json'));
  assert.equal(r.headers.get('Content-Encoding'), 'gzip');
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  assert.deepEqual(JSON.parse(gunzipSync(Buffer.from(await r.arrayBuffer()))), data);
  assert.equal((await relay.fetch(req('GET', '/file/stock/9999.json'))).status, 404);
});

test('上傳路徑要安全', async () => {
  for (const p of ['../x.json', 'a.txt', '', 'stock/..%2Fx.json']) {
    const r = await relay.fetch(new Request(`https://relay.test/put?path=${p}`, { method: 'POST', body: gzipSync('{}'), headers: { 'X-Key': KEY } }));
    assert.equal(r.status, 400, p);
  }
});

test('完成 → ready；當天再加同一檔直接回 ready、不開機器', async () => {
  await call('POST', '/add', { id: '2603' });
  await call('POST', '/claim', undefined, KEY);
  await call('POST', '/done', { id: '2603', ok: true }, KEY);
  assert.equal((await call('GET', '/status?ids=2603')).body.jobs['2603'].status, 'ready');
  clock += 300_000;
  const r = await call('POST', '/add', { id: '2603' });
  assert.equal(r.body.status, 'ready');
  assert.equal(dispatches, 1);
});

test('失敗 → error，而且不會留在每天要更新的名單', async () => {
  await call('POST', '/add', { id: '9999' });
  await call('POST', '/add', { id: '2603' });
  await call('POST', '/claim', undefined, KEY);
  await call('POST', '/done', { id: '9999', ok: false, error: '查無 9999' }, KEY);
  const s = await call('GET', '/status?ids=9999');
  assert.equal(s.body.jobs['9999'].status, 'error');
  assert.equal(s.body.jobs['9999'].error, '查無 9999');
  assert.deepEqual((await call('GET', '/extra')).body.ids, ['2603']);
});

test('代號格式不對會被擋', async () => {
  for (const id of ['', '12', 'abc$', '1234567', '../x']) assert.equal((await call('POST', '/add', { id })).status, 400, id);
  assert.equal(dispatches, 0);
});

test('CORS 預檢', async () => {
  const r = await worker.fetch(new Request('https://relay.test/add', { method: 'OPTIONS' }), {});
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  assert.match(r.headers.get('Access-Control-Allow-Headers'), /X-Key/);
});
