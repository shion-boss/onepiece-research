# -*- coding: utf-8 -*-
"""ローカル /play を 実ブラウザ (Playwright) で操作して人間プレイ層をテストする。

headless fuzz は session API を叩くので React UI 層 (modal/DnD/描画) のバグは見えない。
これは実ブラウザを操作し、 JS コンソールエラー・詰まり・modal 異常を炙り出す。

CJK フォントが無く screenshot の日本語は □ になるが、 DOM の inner_text は読めるので
挙動・状態で検証する。
"""
from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

CHROME = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome")
BASE = "http://localhost:3000"
HUMAN_DECK = sys.argv[1] if len(sys.argv) > 1 else "cardrush_1392"  # イム
AI_DECK = sys.argv[2] if len(sys.argv) > 2 else "cardrush_1342"
MAX_STEPS = int(sys.argv[3]) if len(sys.argv) > 3 else 60

console_msgs: list[str] = []
page_errors: list[str] = []


def run():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=CHROME,
                              args=["--no-sandbox", "--disable-gpu"])
        pg = b.new_page(viewport={"width": 1500, "height": 950})
        pg.on("console", lambda m: console_msgs.append(f"[{m.type}] {m.text}"))
        pg.on("pageerror", lambda e: page_errors.append(str(e)))

        pg.goto(f"{BASE}/play", wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(1500)

        # デッキ選択 (= select 2 つ)。 value = deck slug。
        selects = pg.query_selector_all("select")
        print(f"select 数: {len(selects)}")
        try:
            selects[0].select_option(HUMAN_DECK)
            selects[1].select_option(AI_DECK)
            print(f"deck 選択: human={HUMAN_DECK} ai={AI_DECK}")
        except Exception as e:
            print("deck select 失敗:", e)

        pg.wait_for_timeout(500)
        # 対戦開始 button (text に「開始」)
        start = pg.query_selector("button:has-text('開始')")
        if not start:
            print("開始ボタン 見つからず"); _report(); b.close(); return
        start.click()
        print("対戦開始 click → preload/開始待ち")

        # CardPreloader → board へ。 board の指標 (LOG や 相手/自分) が出るまで待つ
        deadline = time.time() + 40
        while time.time() < deadline:
            txt = pg.inner_text("body")
            if "対戦終了" in txt or "LOG" in txt or "YOU" in txt or "マリガン" in txt:
                break
            pg.wait_for_timeout(800)
        pg.wait_for_timeout(1500)
        pg.screenshot(path="/tmp/play_board.png", full_page=False)
        print("board 到達 screenshot -> /tmp/play_board.png")

        # ループ: modal/ボタンを処理して進める。 詰まり/エラー検出。
        last_sig = None
        same = 0
        for step in range(MAX_STEPS):
            if page_errors:
                print(f"  step{step} ★pageerror 検出 → 中断")
                break
            body = pg.inner_text("body")
            if "YOU WIN" in body or "YOU LOSE" in body or "DRAW" in body:
                print(f"  step{step} 試合終了 検出")
                break
            sig = body[:200]
            same = same + 1 if sig == last_sig else 0
            last_sig = sig
            if same > 12:
                print(f"  step{step} ★同一画面 {same} 回 = 詰まり疑い")
                pg.screenshot(path=f"/tmp/play_stuck_{step}.png")
                break
            acted = _try_act(pg)
            pg.wait_for_timeout(900)
            if not acted:
                # 何も押せない (= AI ターン待ち or DnD 必須) → 少し待つ
                pg.wait_for_timeout(800)

        pg.screenshot(path="/tmp/play_final.png", full_page=False)
        b.close()
    _report()


def _try_act(pg) -> bool:
    """押せる進行ボタン/modal を 1 つ処理。 押せたら True。"""
    # 優先: modal 内の確定/keep/skip/送信、 次に EndPhase 相当
    for sel in [
        "button:has-text('キープ')", "button:has-text('keep')",
        "button:has-text('引き直さ')", "button:has-text('確定')",
        "button:has-text('決定')", "button:has-text('スキップ')",
        "button:has-text('skip')", "button:has-text('おまかせ')",
        "button:has-text('使わない')", "button:has-text('送信')",
        "button:has-text('払わない')", "button:has-text('No Blocker')",
        "button:has-text('防御')", "button:has-text('ターン終了')",
        "button:has-text('EndPhase')", "button:has-text('フェイズ')",
    ]:
        el = pg.query_selector(sel)
        if el and el.is_visible() and el.is_enabled():
            try:
                el.click(timeout=2000)
                return True
            except Exception:
                continue
    # 汎用 fallback: modal overlay (z-50 等の絶対配置) 内の有効ボタンを押す。
    # まず modal 内のカード(候補)を1枚選んでから、 主要ボタンを押す。
    overlay = None
    for ov_sel in ["div.z-50", "div[class*='z-50']", "div[class*='z-[55]']"]:
        cand = pg.query_selector_all(ov_sel)
        for c in cand:
            try:
                if c.is_visible():
                    overlay = c
                    break
            except Exception:
                pass
        if overlay:
            break
    if overlay:
        # 候補カードを1枚クリック (= search/target/reorder modal 用)
        try:
            cardbtn = overlay.query_selector("button:has(img)")
            if cardbtn and cardbtn.is_enabled():
                cardbtn.click(timeout=1500)
        except Exception:
            pass
        # modal 内の有効ボタンを 末尾 から クリック (= 主要 action)
        btns = overlay.query_selector_all("button")
        for el in reversed(btns):
            try:
                if el.is_visible() and el.is_enabled():
                    el.click(timeout=1500)
                    return True
            except Exception:
                continue
    return False


def _report():
    errs = [m for m in console_msgs if m.startswith("[error]")]
    warns = [m for m in console_msgs if m.startswith("[warning]")]
    print("\n=== 結果 ===")
    print(f"console error: {len(errs)} / warning: {len(warns)} / pageerror: {len(page_errors)}")
    for e in page_errors[:10]:
        print("  PAGEERROR:", e[:200])
    for e in errs[:15]:
        print("  ", e[:200])
    if not errs and not page_errors:
        print("  JS エラーなし")


if __name__ == "__main__":
    run()
