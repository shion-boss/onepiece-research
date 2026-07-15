#!/usr/bin/env python3
"""DATABASE_URL の疎通 + テーブル一覧を確認する (= Neon/Postgres 接続チェック)。

秘密情報 (接続文字列 = パスワード入り) は一切出力しない。 出るのは「接続 OK/失敗」と
public スキーマのテーブル名だけ。

使い方:
    # .env.local からファイル指定で
    .venv/bin/python scripts/check_db.py /path/to/.env.local
    # もしくは env に入れて
    DATABASE_URL='postgres://...' .venv/bin/python scripts/check_db.py
"""
import os
import sys


def load_from_env_file(path: str):
    """.env / .env.local から DATABASE_URL の値を取り出す (クォート除去)。"""
    try:
        for raw in open(path, encoding="utf-8"):
            line = raw.strip()
            if line.startswith("DATABASE_URL="):
                val = line[len("DATABASE_URL="):].strip()
                if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
                    val = val[1:-1]
                return val
    except FileNotFoundError:
        print(f"ファイルが見つかりません: {path}")
        sys.exit(1)
    return None


url = load_from_env_file(sys.argv[1]) if len(sys.argv) > 1 else None
url = url or os.environ.get("DATABASE_URL")

if not url:
    print("DATABASE_URL が見つかりません。 .env.local のパスを引数で渡すか env にセットしてください。")
    sys.exit(1)

# ホスト名だけ安全に表示 (パスワードは出さない)。
try:
    host = url.split("@", 1)[1].split("/", 1)[0]
    print(f"接続先ホスト: {host}")
except Exception:
    pass

try:
    import psycopg
except ImportError:
    print("psycopg 未インストール。 次を実行: .venv/bin/pip install 'psycopg[binary]'")
    sys.exit(2)

try:
    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
            tables = [r[0] for r in cur.fetchall()]
    print("=> 接続 OK")
    print("=> 既存テーブル:", tables if tables else "(なし = 空のDB)")
except Exception as e:
    print("=> 接続 失敗:", type(e).__name__, str(e)[:200])
    sys.exit(3)
