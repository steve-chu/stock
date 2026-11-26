"""手機「新增股票」時，GitHub 開一台機器跑這支：
向中繼站領工作 → 幾檔一起抓資料、計算 → 結果傳回中繼站 → 再領一次，
做的時候又有人新增，就順便一起做；閒置一陣子沒新工作才關機。"""
import gzip
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import build  # noqa: E402  共用每日建置的計算（compute_one、quote_one）

RELAY = build.relay_url()
KEY = os.environ["RUNNER_KEY"]
IDLE_EXIT = int(os.environ.get("IDLE_EXIT", "30"))     # 沒新工作多少秒就關機
MAX_RUN = int(os.environ.get("MAX_RUN", "1200"))       # 一台最多跑多久（秒）
WORKERS = int(os.environ.get("WORKERS", "3"))          # 同時處理幾檔

from fastapi import HTTPException  # noqa: E402

H = {"X-Key": KEY}


def call(path, headers=None, **kw):
    for i in range(3):
        try:
            r = requests.post(RELAY + path, headers={**H, **(headers or {})}, timeout=30, **kw)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == 2:
                raise
            time.sleep(2)


def put(path, obj):
    body = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    call("/put", params={"path": path}, data=body, headers={"Content-Type": "application/octet-stream"})


def one(sid):
    t = time.time()
    try:
        build.core.watchlist_add({"stock_id": sid})   # 抓股價（代號不存在會在這裡失敗）
        files = build.compute_one(sid)                 # 抓財報等、算分析、回測
        for path, obj in files.items():
            put(path, obj)
        put(f"quote/{sid}.json", build.quote_one(sid))
        call("/done", json={"id": sid, "ok": True})
        print(f"{sid} 完成 {time.time() - t:.1f}s", flush=True)
    except HTTPException as e:
        call("/done", json={"id": sid, "ok": False, "error": str(e.detail)})
        print(f"{sid} 失敗：{e.detail}", flush=True)
    except Exception as e:
        traceback.print_exc()
        call("/done", json={"id": sid, "ok": False, "error": f"計算失敗：{e}"})


def main():
    build.ds.init_db()
    if not build.OFFLINE:
        try:
            build.ds.ensure_stock_info()
        except Exception as e:
            print("股票名稱更新失敗（不影響）：", e)
    t0, idle_since = time.time(), time.time()
    with ThreadPoolExecutor(WORKERS) as pool:
        running = set()
        while time.time() - t0 < MAX_RUN:
            ids = call("/claim").get("ids", [])      # 領工作，同時告訴中繼站「我還在」
            for sid in ids:
                print("領到", sid, flush=True)
                running.add(pool.submit(one, sid))
            running = {f for f in running if not f.done()}
            if ids or running:
                idle_since = time.time()
            elif time.time() - idle_since > IDLE_EXIT:
                break
            time.sleep(2)
        for f in as_completed(running):
            pass
    print(f"結束，共 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
