"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSavedFilters, normalizeFilterQuery } from "@/lib/savedFilters";
import { useIsGuest } from "@/lib/useIsGuest";
import { LoginButton, LockIcon } from "./LoginButton";

// カード view の左メニュー: すべて開く + 保存済み絞り込みの一覧 + 現在の絞り込みを保存。
export function CardsSidebar() {
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const isGuest = useIsGuest();
  const { filters, add, remove, rename } = useSavedFilters();

  const onCards = pathname === "/cards";
  const currentQuery = normalizeFilterQuery(new URLSearchParams(params.toString()));
  const hasCurrentFilter = onCards && currentQuery.length > 0;

  const save = () => {
    if (!hasCurrentFilter) return;
    const name = window.prompt("この絞り込みに名前を付けて保存");
    if (name && name.trim()) add(name, currentQuery);
  };

  return (
    <div className="py-2">
      <div className="flex items-center justify-between px-4 pb-1 pt-1">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[color:var(--text-muted)]">
          カード
        </span>
      </div>
      <Link
        href="/cards"
        className={`block px-4 py-1.5 text-[13px] hover:bg-[var(--list-hover)] hover:text-white ${
          onCards && currentQuery === ""
            ? "bg-[var(--list-hover)] text-white"
            : "text-[color:var(--text-default)]"
        }`}
      >
        すべてのカードを開く
      </Link>

      <div className="flex items-center justify-between px-4 pb-1 pt-3">
        <span className="text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">
          保存した絞り込み
        </span>
        {isGuest ? (
          // ゲスト: 絞り込み保存はユーザー情報が要る → ログイン必須。 ロック表示 + 誘導。
          <LoginButton
            title="ログインすると絞り込み条件を保存できます"
            className="flex items-center rounded px-1.5 text-[color:var(--text-muted)] hover:bg-[var(--list-hover)] hover:text-[color:var(--warning)]"
          >
            <LockIcon />
          </LoginButton>
        ) : (
          <button
            type="button"
            onClick={save}
            disabled={!hasCurrentFilter}
            title={hasCurrentFilter ? "現在の絞り込みを保存" : "カード検索で条件を設定すると保存できます"}
            className="rounded px-1.5 text-lg leading-none text-[color:var(--text-muted)] hover:bg-[var(--list-hover)] hover:text-white disabled:opacity-30 disabled:hover:bg-transparent"
          >
            +
          </button>
        )}
      </div>

      {filters.length === 0 ? (
        <p className="px-4 py-1 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          {isGuest
            ? "ログインすると、絞り込み条件を名前付きで保存できます。"
            : "カード検索で絞り込んで「+」を押すと、その条件を名前付きで保存できます。"}
        </p>
      ) : (
        filters.map((f) => {
          const active = onCards && currentQuery === f.query;
          return (
            <div
              key={f.id}
              className={`group flex items-center gap-1 pr-2 text-[13px] ${
                active ? "bg-[var(--list-hover)]" : "hover:bg-[var(--list-hover)]"
              }`}
            >
              <button
                type="button"
                onClick={() => router.push(f.query ? `/cards?${f.query}` : "/cards")}
                className={`flex min-w-0 flex-1 items-center gap-2 px-4 py-1.5 text-left ${
                  active ? "text-white" : "text-[color:var(--text-default)] group-hover:text-white"
                }`}
                title={f.query}
              >
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 opacity-70">
                  <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" />
                </svg>
                <span className="truncate">{f.name}</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  const name = window.prompt("名前を変更", f.name);
                  if (name && name.trim()) rename(f.id, name);
                }}
                title="名前を変更"
                className="hidden h-5 w-5 items-center justify-center rounded text-[color:var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-white group-hover:flex"
              >
                <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                </svg>
              </button>
              <button
                type="button"
                onClick={() => remove(f.id)}
                title="削除"
                className="hidden h-5 w-5 items-center justify-center rounded text-[color:var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-white group-hover:flex"
              >
                <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>
          );
        })
      )}
    </div>
  );
}
