"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthControls } from "./AuthControls";

// pub=true は公開デプロイ (NEXT_PUBLIC_PUBLIC_MODE=1) でも出すもの。 研究系 (コンボ探索/研究/
// メタ分析) は公開モードでは隠す (= API 側も PUBLIC_MODE で 403、 二重で締める)。 ローカルは全表示。
const ALL_NAV = [
  { href: "/cards", label: "カード", pub: true },
  { href: "/combos", label: "コンボ探索", pub: false },
  { href: "/decks", label: "デッキ", pub: true },
  { href: "/play", label: "対戦", pub: true },
  { href: "/research", label: "研究", pub: false },
  { href: "/meta", label: "メタ分析", pub: false },
  { href: "/faq", label: "Q&A", pub: true },
] as const;

const PUBLIC_MODE = process.env.NEXT_PUBLIC_PUBLIC_MODE === "1";
const NAV = PUBLIC_MODE ? ALL_NAV.filter((n) => n.pub) : ALL_NAV;

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
    <aside
      className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r"
      style={{ background: "var(--sidebar-bg)", borderColor: "var(--border-1)" }}
    >
      <Link
        href="/"
        className="flex items-center gap-2.5 border-b px-3 py-3 transition-colors hover:bg-[var(--list-hover)]"
        style={{ borderColor: "var(--border-1)" }}
      >
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-[11px] font-bold text-white"
          style={{ background: "var(--brand)" }}
          aria-hidden
        >
          OP
        </span>
        <span className="text-[13px] font-semibold tracking-tight text-[var(--text-strong)]">
          OPTCG
        </span>
      </Link>
      <div className="px-3 pb-1 pt-3 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
        メニュー
      </div>
      <nav className="flex flex-col" aria-label="メインナビゲーション">
        {NAV.map(({ href, label }) => {
          const active = path === href || path.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`px-4 py-1.5 text-[13px] transition-colors ${
                active
                  ? "border-l-2 border-[var(--brand)] bg-[var(--brand-soft)] pl-[calc(1rem-2px)] text-white"
                  : "text-[var(--text-default)] hover:bg-[var(--list-hover)] hover:text-white"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div
        className="mt-auto flex flex-col gap-2 border-t px-3 py-2.5"
        style={{ borderColor: "var(--border-1)" }}
      >
        <AuthControls />
      </div>
    </aside>
  );
}
