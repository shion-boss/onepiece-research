"use client";

import { useCardCount } from "@/lib/cardCount";

// ヘッダ右上の件数表示。 CardBrowser が絞り込み後件数を publish するのでそれを表示。
// 未マウント時 (count=null) は fallback (= server が取得した全件数) を出す。
export function CardCountBadge({ fallback }: { fallback: number }) {
  const count = useCardCount((s) => s.count);
  const n = count ?? fallback;
  return <div className="text-sm text-[color:var(--text-muted)]">{n} 件</div>;
}
