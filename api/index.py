# -*- coding: utf-8 -*-
"""
Vercel Python Function entry point for FastAPI.

vercel.json の rewrites で /api/* を全てこの function に流す。
Vercel の Python runtime は ASGI handler `app` を自動 detect する。

api/main.py が本体 (= 2700+ 行)、 ここは re-export のみ。 ローカル開発時は
従来通り `uvicorn api.main:app --reload` でも動く。

sys.path 操作: Vercel Python runtime は api/index.py を直接実行するため、
親ディレクトリ (= repo root) を sys.path に明示追加して `from api.main import app`
+ `from engine.* import ...` 等が解決できるようにする。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from api.main import app  # noqa: E402, F401

# Vercel が `app` (= ASGI handler) を 認識して呼び出す。
