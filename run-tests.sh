#!/usr/bin/env bash
# 本機跑全部測試（和 GitHub 上一樣）。用法：./run-tests.sh        只跑 chromium：E2E_BROWSERS=chromium ./run-tests.sh
set -euo pipefail
cd "$(dirname "$0")"
echo "== 中繼站 ==";            node --test worker/test/*.test.mjs
echo "== 分析與建置 ==";        python3 -m pytest tests --ignore=tests/e2e -q
echo "== 手機畫面 ==";          python3 -m pytest tests/e2e -q
