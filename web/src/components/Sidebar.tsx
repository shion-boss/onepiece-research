"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/cards", label: "カード" },
  { href: "/decks", label: "デッキ" },
  { href: "/meta", label: "メタ分析" },
  { href: "/faq", label: "Q&A" },
] as const;

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="sticky top-0 flex h-screen w-48 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
      <Link
        href="/"
        className="flex items-center gap-2 border-b border-zinc-200 px-4 py-4 transition-colors hover:bg-zinc-100 dark:border-zinc-800 dark:hover:bg-zinc-900"
      >
        <div>
          <div className="text-sm font-bold leading-tight tracking-tight text-zinc-900 dark:text-zinc-100">
            One Piece
          </div>
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400">Research</div>
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
            >
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
