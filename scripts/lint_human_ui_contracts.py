# -*- coding: utf-8 -*-
"""人間vsAI UI 契約の静的リンタ (= headless fuzzer が見られない層を CI で守る)。

ヘッドレス fuzzer は engine 経路を叩くので React レンダリングのバグ
(= 描画されない dead component に操作 UI が埋もれる / modal の payload キー不一致で
空表示) を捕まえられない。 これらを **静的解析** で検出する。 2026-06-04 追加。

検査:
  C1 dead component: `function XxxModal/Panel/Overlay` が JSX で一度も使われていない。
       (= ブロッカー選択が dead な DefenseOverlay に埋もれていた類型)
  C2 kind カバレッジ: engine が立てる pending_choice.kind 全てに UI の分岐がある。
  C3 payload キー契約: 各 kind について engine が書く list キー (cards/candidates/
       options) を、 その kind を描画する modal が実際に読んでいる。
       (= シュガーの「candidates を入れたのに modal は cards を読む」 空表示 類型)

exit 1 で違反報告。 pytest からも呼ぶ (tests/test_human_ui_contracts.py)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "web" / "src" / "components" / "HumanMatchPlay.tsx"
ENGINE_FILES = [
    ROOT / "engine" / "effects.py",
    ROOT / "engine" / "human_session.py",
    ROOT / "engine" / "game.py",
    ROOT / "engine" / "core.py",
]

LIST_KEYS = ("candidates", "cards", "options")


def engine_kind_listkey() -> dict[str, set[str]]:
    """engine が立てる pending kind → 書く list キー集合。"""
    out: dict[str, set[str]] = {}
    for f in ENGINE_FILES:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r'"kind":\s*"([a-z_]+)"', src):
            kind = m.group(1)
            seg = src[m.start(): m.start() + 700]
            keys = {k for k in LIST_KEYS if re.search(rf'"{k}"\s*:', seg)}
            out.setdefault(kind, set()).update(keys)
    return out


def ui_text() -> str:
    return UI.read_text(encoding="utf-8")


def ui_kinds(src: str) -> set[str]:
    return set(re.findall(r'pending_payload\.kind === "([a-z_]+)"', src))


def ui_kind_component(src: str) -> dict[str, str]:
    """kind → それを描画する Component 名 (= `kind === "X" ? ... <Component`)。"""
    out: dict[str, str] = {}
    for m in re.finditer(r'pending_payload\.kind === "([a-z_]+)"\s*\?', src):
        kind = m.group(1)
        seg = src[m.end(): m.end() + 400]
        cm = re.search(r"<([A-Z][A-Za-z0-9]+)\b", seg)
        if cm:
            out[kind] = cm.group(1)
    return out


def component_listkeys(src: str) -> dict[str, set[str]]:
    """Component 名 → その関数本体で読む payload list キー集合。"""
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"\nfunction ([A-Z][A-Za-z0-9]+)\(", src):
        name = m.group(1)
        body = src[m.start(): m.start() + 1600]
        keys = set(re.findall(r"payload[?]?\.(candidates|cards|options)\b", body))
        out[name] = keys
    return out


def all_components(src: str) -> list[str]:
    return re.findall(r"\nfunction ([A-Z][A-Za-z0-9]*(?:Modal|Panel|Overlay))\(", src)


def main() -> int:
    src = ui_text()
    eng = engine_kind_listkey()
    uik = ui_kinds(src)
    k2c = ui_kind_component(src)
    c2k = component_listkeys(src)
    violations: list[str] = []

    # C1 dead component
    for comp in all_components(src):
        if not re.search(rf"<{comp}\b", src):
            violations.append(
                f"C1 dead component: {comp} が JSX で 未使用 "
                f"(= 操作 UI が埋もれている恐れ。 削除 or 配線せよ)"
            )

    # C2 kind カバレッジ
    for kind in sorted(eng):
        if kind not in uik:
            violations.append(
                f"C2 未対応 kind: engine が pending '{kind}' を立てるが UI に分岐なし "
                f"(= UnknownPendingChoiceModal 行き)"
            )

    # C3 payload キー契約
    for kind, eng_keys in sorted(eng.items()):
        if not eng_keys or kind not in k2c:
            continue
        comp = k2c[kind]
        read = c2k.get(comp, set())
        # engine が書く list キーのうち、 modal が一つも読まないなら不一致
        if eng_keys and not (eng_keys & read):
            violations.append(
                f"C3 payload キー不一致: kind '{kind}' は engine が {sorted(eng_keys)} を書くが "
                f"描画 modal {comp} は {sorted(read) or '(list キー読まず)'} を読む "
                f"(= 空表示の恐れ)"
            )

    if violations:
        print(f"!!! UI 契約 違反 {len(violations)} 件:")
        for v in violations:
            print("  -", v)
        return 1
    print("OK: dead component なし / 全 pending kind に UI 分岐あり / payload キー契約一致")
    print(f"  (engine kinds={len(eng)}, UI 分岐={len(uik)}, components={len(all_components(src))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
