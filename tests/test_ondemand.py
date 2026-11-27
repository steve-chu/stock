"""手機新增股票：假的中繼站＋真的 ondemand.py。
確認：同一台機器一次領好幾檔、跑到一半新增的也接著做、結果檔都有上傳、錯的代號會回報失敗。"""
import gzip
import json
import os
import subprocess
import sys
import threading
from urllib.parse import unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import run_env, stock_ids

KEY = "test-key"


class Relay:
    def __init__(self, first, later):
        self.queue, self.later = list(first), list(later)
        self.claims, self.files, self.done, self.bad_key = [], {}, {}, 0
        self.lock = threading.Lock()


def serve(relay):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            if self.headers.get("X-Key") != KEY:
                relay.bad_key += 1
                return self._send({"error": "forbidden"}, 403)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            with relay.lock:
                if self.path == "/claim":
                    ids, relay.queue = relay.queue, []
                    if relay.claims and relay.later:   # 機器跑第二次領工作時，有人又新增了
                        ids, relay.later = ids + relay.later, []
                    relay.claims.append(ids)
                    return self._send({"ids": ids})
                if self.path.startswith("/put?path="):
                    path = unquote(self.path.split("=", 1)[1])
                    relay.files[path] = json.loads(gzip.decompress(body))
                    return self._send({"ok": True})
                if self.path == "/done":
                    d = json.loads(body)
                    relay.done[d["id"]] = d
                    return self._send({"ok": True})
            self._send({"error": "not found"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_batch_one_machine(built):
    ids = stock_ids()
    first, later = [ids[1], ids[2]], [ids[3], "ZZZZ9"]
    relay = Relay(first, later)
    srv = serve(relay)
    try:
        env = run_env(RELAY_URL=f"http://127.0.0.1:{srv.server_port}", RUNNER_KEY=KEY, IDLE_EXIT="4", WORKERS="3")
        r = subprocess.run([sys.executable, "ondemand.py"], cwd=built, env=env, capture_output=True, text=True, timeout=600)
        print(r.stdout[-2000:], r.stderr[-2000:])
        assert r.returncode == 0
    finally:
        srv.shutdown()
    assert relay.bad_key == 0
    assert relay.claims[0] == first, "第一次就要一起領走兩檔"
    assert any(set(later) <= set(c) for c in relay.claims[1:]), "跑到一半新增的要由同一台接著做"
    for sid in first + [ids[3]]:
        assert relay.done[sid]["ok"], relay.done[sid]
        for p in (f"stock/{sid}.json", f"stock/{sid}.alt.json", f"bars/{sid}_W.json", f"bars/{sid}_M.json", f"lbt/{sid}.json", f"quote/{sid}.json"):
            assert p in relay.files, f"沒上傳 {p}"
        assert relay.files[f"quote/{sid}.json"]["close"] > 0
    assert relay.done["ZZZZ9"]["ok"] is False and relay.done["ZZZZ9"]["error"]


def test_relay_url_from_file(built, monkeypatch):
    monkeypatch.delenv("RELAY_URL", raising=False)
    out = subprocess.run([sys.executable, "-c", "import build;print(build.relay_url())"], cwd=built, env=run_env(),
                         capture_output=True, text=True).stdout.strip().splitlines()[-1]
    p = os.path.join(built, "relay.txt")
    want = open(p).read().split("#")[0].strip().rstrip("/") if os.path.exists(p) else ""
    assert out == want
