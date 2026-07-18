#!/usr/bin/env python3
"""Scrape the pros_02 note.com creator (paid OPTCG deck guides) into db/note_pros02/.

Modes:
  list    Paginate the PUBLIC contents API -> db/note_pros02/catalog.json
          (metadata only: key/title/price/date. No auth needed.)
  login   Playwright headless Google login -> save storage_state to
          db/note_pros02/.auth/state.json. Reads creds from .env (never printed).
  fetch   For every catalog key without a saved body, GET the note detail API
          with the authenticated session and save db/note_pros02/bodies/<key>.json.
          Auth source = storage_state (from `login`) OR env NOTE_SESSION_COOKIE.
          Checkpointed + resumable: skips keys already fetched, polite sleep.

Secrets: NOTE_GOOGLE_EMAIL / NOTE_GOOGLE_PASSWORD / NOTE_SESSION_COOKIE are read
from the environment / .env and are NEVER printed or written to the catalog/bodies.

Usage:
  .venv/bin/python scripts/scrape_note_pros02.py list
  .venv/bin/python scripts/scrape_note_pros02.py login
  .venv/bin/python scripts/scrape_note_pros02.py fetch [--limit N] [--sleep 1.0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "db" / "note_pros02"
BODIES = OUT / "bodies"
CATALOG = OUT / "catalog.json"
AUTH_STATE = OUT / ".auth" / "state.json"
CREATOR = "pros_02"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _load_env() -> None:
    """Load .env / .env.local KEY=VALUE into os.environ (do not overwrite existing)."""
    for fn in (".env", ".env.local"):
        p = ROOT / fn
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


# --------------------------------------------------------------------------- list
def mode_list() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    page = 1
    with httpx.Client(headers={"User-Agent": UA}, timeout=30) as cli:
        while True:
            r = cli.get(
                f"https://note.com/api/v2/creators/{CREATOR}/contents",
                params={"kind": "note", "page": page},
            )
            r.raise_for_status()
            d = r.json()["data"]
            for n in d.get("contents", []):
                items.append({
                    "key": n.get("key"),
                    "title": n.get("name"),
                    "price": n.get("price"),
                    "publish_at": n.get("publishAt") or n.get("publish_at"),
                    "type": n.get("type"),
                    "like_count": n.get("likeCount"),
                    "membership": bool(n.get("membership")),
                })
            if d.get("isLastPage"):
                break
            page += 1
            time.sleep(0.3)
    CATALOG.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    paid = sum(1 for x in items if (x["price"] or 0) > 0)
    print(f"catalog: {len(items)} notes ({paid} paid / {len(items)-paid} free) -> {CATALOG.relative_to(ROOT)}")


# -------------------------------------------------------------------------- login
def mode_login() -> None:
    """Automate Google login to note.com and persist cookies. Fragile: headless
    Google login is often blocked. On failure use the NOTE_SESSION_COOKIE path."""
    from playwright.sync_api import sync_playwright  # lazy import

    email = os.environ.get("NOTE_GOOGLE_EMAIL")
    pw = os.environ.get("NOTE_GOOGLE_PASSWORD")
    if not email or not pw:
        print("ERR: NOTE_GOOGLE_EMAIL / NOTE_GOOGLE_PASSWORD not set", file=sys.stderr)
        sys.exit(2)
    AUTH_STATE.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="ja-JP")
        pg = ctx.new_page()
        pg.goto("https://note.com/login", wait_until="domcontentloaded", timeout=60000)
        # Click the Google login button (label varies; try several selectors).
        for sel in ("text=Googleでログイン", "text=Google", "[data-provider=google]",
                    "button:has-text('Google')", "a:has-text('Google')"):
            try:
                pg.click(sel, timeout=4000)
                break
            except Exception:
                continue
        try:
            pg.wait_for_url("**accounts.google.com/**", timeout=15000)
            pg.fill("input[type=email]", email, timeout=15000)
            pg.click("#identifierNext, button:has-text('次へ'), button:has-text('Next')")
            pg.fill("input[type=password]", pw, timeout=20000)
            pg.click("#passwordNext, button:has-text('次へ'), button:has-text('Next')")
            pg.wait_for_url("**note.com/**", timeout=45000)
        except Exception as e:
            # Google likely blocked the automated/headless login (2FA / bot check).
            print(f"login FAILED at Google step: {type(e).__name__}. "
                  f"Headless Google login was probably blocked. "
                  f"Use the NOTE_SESSION_COOKIE fallback instead.", file=sys.stderr)
            try:
                pg.screenshot(path=str(OUT / "login_debug.png"))
            except Exception:
                pass
            browser.close()
            sys.exit(1)
        ctx.storage_state(path=str(AUTH_STATE))
        browser.close()
    print(f"login OK -> storage_state saved ({AUTH_STATE.relative_to(ROOT)})")


# -------------------------------------------------------------------------- fetch
def _cookies_from_state() -> dict:
    if not AUTH_STATE.exists():
        return {}
    st = json.loads(AUTH_STATE.read_text(encoding="utf-8"))
    return {c["name"]: c["value"] for c in st.get("cookies", [])
            if "note.com" in (c.get("domain") or "")}


def _build_cookie_jar() -> dict:
    """Assemble note.com auth cookies from every supported source, robustly:
    storage_state, NOTE_SESSION_COOKIE (full 'a=b; c=d' header OR a bare token
    value), and standalone env vars note_gql_auth_token / _note_session_v5."""
    jar: dict[str, str] = {}
    jar.update(_cookies_from_state())
    raw = (os.environ.get("NOTE_SESSION_COOKIE") or "").strip()
    if raw:
        if "=" in raw:  # full or partial cookie header
            for part in raw.split(";"):
                if "=" in part:
                    n, _, v = part.strip().partition("=")
                    if n.strip() and v.strip():
                        jar[n.strip()] = v.strip()
        else:  # bare value -> assume it's the gql auth token
            jar["note_gql_auth_token"] = raw
    for name in ("note_gql_auth_token", "_note_session_v5"):
        v = os.environ.get(name)
        if v and name not in jar:
            jar[name] = v.strip()
    return jar


def mode_fetch(limit: int | None, sleep_s: float) -> None:
    if not CATALOG.exists():
        print("ERR: run `list` first (no catalog.json)", file=sys.stderr)
        sys.exit(2)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    BODIES.mkdir(parents=True, exist_ok=True)

    cookies = _build_cookie_jar()
    if not cookies:
        print("ERR: no auth. Run `login` (storage_state) or set NOTE_SESSION_COOKIE "
              "/ note_gql_auth_token / _note_session_v5 in .env.", file=sys.stderr)
        sys.exit(2)
    print(f"auth cookies loaded: {sorted(cookies.keys())}")  # names only, no values

    headers = {"User-Agent": UA}

    todo = [n for n in catalog if n.get("key")
            and not (BODIES / f"{n['key']}.json").exists()]
    if limit:
        todo = todo[:limit]
    print(f"fetch: {len(todo)} notes to fetch (of {len(catalog)} total)")

    ok = locked = err = 0
    with httpx.Client(headers=headers, cookies=cookies or None, timeout=30) as cli:
        for i, n in enumerate(todo, 1):
            key = n["key"]
            try:
                r = cli.get(f"https://note.com/api/v3/notes/{key}")
                r.raise_for_status()
                data = r.json().get("data", {})
                can = data.get("can_read", data.get("canRead"))
                body = data.get("body") or ""
                rec = {
                    "key": key, "title": data.get("name") or n.get("title"),
                    "price": data.get("price"), "can_read": can,
                    "publish_at": data.get("publishAt") or n.get("publish_at"),
                    "body_html": body, "body_len": len(body),
                }
                (BODIES / f"{key}.json").write_text(
                    json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
                if body:
                    ok += 1
                else:
                    locked += 1
            except Exception as e:
                err += 1
                print(f"  ! {key}: {type(e).__name__} {str(e)[:120]}", file=sys.stderr)
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  ok={ok} locked={locked} err={err}")
            time.sleep(sleep_s)
    print(f"fetch done: ok(body)={ok} locked(no body)={locked} err={err}")
    if locked and not ok:
        print("All locked = auth not effective (cookie expired / not subscribed to this content).",
              file=sys.stderr)


def main() -> None:
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["list", "login", "fetch"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    if a.mode == "list":
        mode_list()
    elif a.mode == "login":
        mode_login()
    elif a.mode == "fetch":
        mode_fetch(a.limit, a.sleep)


if __name__ == "__main__":
    main()
