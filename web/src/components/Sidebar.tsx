"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/cards", label: "カード" },
  { href: "/decks", label: "デッキ" },
  { href: "/play", label: "対戦" },
  { href: "/research", label: "研究" },
  { href: "/meta", label: "メタ分析" },
  { href: "/faq", label: "Q&A" },
] as const;

export function Sidebar() {
  const path = usePathname();
  // /play で 対戦 開始済 (= board 表示中) なら sidebar 非表示 (= fullscreen)。
  // 開始前 (= StartPanel) は 表示。 HumanMatchPlay が window event で 通知する。
  const [matchActive, setMatchActive] = useState(false);
  useEffect(() => {
    function onChange(e: Event) {
      setMatchActive((e as CustomEvent<boolean>).detail === true);
    }
    window.addEventListener("match-state-change", onChange as EventListener);
    return () =>
      window.removeEventListener("match-state-change", onChange as EventListener);
  }, []);
  // path 変化 で reset (= 別 ページ 行ったら 開始済 flag 消える)
  useEffect(() => {
    if (!path?.startsWith("/play")) setMatchActive(false);
  }, [path]);
  if (path?.startsWith("/play") && matchActive) return null;
  return (
    <aside className="sticky top-0 flex h-screen w-52 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
      <Link
        href="/"
        className="flex items-center gap-3 border-b border-zinc-200 px-4 py-4 transition-colors hover:bg-zinc-100 dark:border-zinc-800 dark:hover:bg-zinc-900"
      >
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-sm font-bold tracking-tight text-white"
          style={{
            background:
              "linear-gradient(135deg, var(--brand-strong) 0%, var(--brand) 60%, var(--accent) 100%)",
            boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          }}
          aria-hidden
        >
          OP
        </div>
        <div className="leading-tight">
          <div className="text-sm font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            ワンピース
          </div>
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
            カード研究所
          </div>
        </div>
      </Link>
      <nav
        className="flex flex-col gap-0.5 p-2 pt-3"
        aria-label="メインナビゲーション"
      >
        {NAV.map(({ href, label }) => {
          const active = path === href || path.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-zinc-200 font-medium text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
                  : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-100"
              }`}
              style={
                active
                  ? { borderLeft: "2px solid var(--brand)", paddingLeft: "calc(0.75rem - 2px)" }
                  : undefined
              }
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto border-t border-zinc-200 px-4 py-3 text-[10px] text-zinc-400 dark:border-zinc-800 dark:text-zinc-600">
        Research Platform
      </div>
    </aside>
  );
}
