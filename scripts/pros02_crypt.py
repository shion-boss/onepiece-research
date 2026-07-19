#!/usr/bin/env python3
"""pros_02 有料 brief を暗号化して repo に置く (公開 repo でも人間が読めない ciphertext)。

cloud teacher routine が env var `PROS02_KEY` で復号して使う = 有料 prose を一切公開せず
full 活用する仕組み ([[project_note_pros02_ingestion]])。 ohtsuki 方針 = 有料原本はフル活用
だが「人間が見なければ問題ない」→ 公開 repo には ciphertext のみ、 復号鍵は私的 env var。

- 鍵 = `db/note_pros02/.pros02_key` (gitignore) に生成。 ohtsuki が同値を claude.ai の環境変数
  `PROS02_KEY` に設定 → cloud が復号可能に。 **鍵は絶対に repo にも stdout にも出さない**。
- `genkey`  : 鍵ファイルを生成 (既存なら上書きしない)。
- `encrypt` : teacher_briefs/*.md + general_teacher_brief.md を db/note_pros02/enc/*.enc に暗号化 (=commit対象)。
- `decrypt <name>` : `PROS02_KEY` で enc/<name>.enc を復号し stdout へ (cloud routine が読む)。

このスクリプト自体は鍵を含まないので commit 安全。
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
NP = ROOT / "db" / "note_pros02"
ENC = NP / "enc"
KEYFILE = NP / ".pros02_key"


def _key() -> bytes:
    """env (cloud) 優先、 無ければ local keyfile (私の encrypt 時)。"""
    k = os.environ.get("PROS02_KEY")
    if k:
        return k.encode() if isinstance(k, str) else k
    if KEYFILE.exists():
        return KEYFILE.read_bytes().strip()
    raise SystemExit("PROS02_KEY env も keyfile も無い (genkey で鍵を作るか env を設定)")


def cmd_genkey() -> None:
    if KEYFILE.exists():
        print(f"keyfile 既存 (上書きしない): {KEYFILE}")
        return
    NP.mkdir(parents=True, exist_ok=True)
    KEYFILE.write_bytes(Fernet.generate_key())
    print(f"鍵生成: {KEYFILE}")
    print("→ この値を claude.ai の環境変数 PROS02_KEY に設定してください (中身は表示しません)。")


def cmd_encrypt() -> None:
    f = Fernet(_key())
    ENC.mkdir(parents=True, exist_ok=True)
    srcs = sorted(glob.glob(str(NP / "teacher_briefs" / "*.md")))
    gb = NP / "general_teacher_brief.md"
    if gb.exists():
        srcs.append(str(gb))
    n = 0
    for s in srcs:
        name = Path(s).stem  # cardrush_1454 / general_teacher_brief
        (ENC / f"{name}.enc").write_bytes(f.encrypt(Path(s).read_bytes()))
        n += 1
    print(f"暗号化 {n} 件 → {ENC} (ciphertext = commit 対象)")


def cmd_decrypt(name: str) -> None:
    f = Fernet(_key())
    p = ENC / f"{name}.enc"
    if not p.exists():
        raise SystemExit(f"not found: {p}")
    sys.stdout.write(f.decrypt(p.read_bytes()).decode("utf-8"))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "genkey":
        cmd_genkey()
    elif cmd == "encrypt":
        cmd_encrypt()
    elif cmd == "decrypt" and len(sys.argv) > 2:
        cmd_decrypt(sys.argv[2])
    else:
        print("usage: pros02_crypt.py genkey | encrypt | decrypt <name>")


if __name__ == "__main__":
    main()
