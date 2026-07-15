"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { renameDeck, deleteDeck } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";

// デッキ詳細ページの操作 (名前変更 / 削除)。 自作デッキのみ表示する (メタは backend 保護)。
export function DeckActions({ slug, name }: { slug: string; name: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const onRename = async () => {
    const next = window.prompt("デッキ名を変更", name);
    if (!next || !next.trim() || next.trim() === name) return;
    setBusy(true);
    try {
      await renameDeck(slug, next.trim());
      useWorkspace.getState().refreshDecks(); // 左メニュー即更新
      router.refresh(); // 詳細ページの表示名を更新
    } catch {
      window.alert("名前を変更できませんでした。自分で作成したデッキのみ変更できます。");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    if (!window.confirm(`「${name}」を削除しますか？ この操作は取り消せません。`)) return;
    setBusy(true);
    try {
      await deleteDeck(slug);
      useWorkspace.getState().refreshDecks(); // 左メニューから消す
      router.push("/decks"); // 一覧へ戻る
    } catch {
      window.alert("削除できませんでした。自分で作成したデッキのみ削除できます。");
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={onRename}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--border-2)] px-3 py-1.5 text-sm text-[color:var(--text-default)] transition hover:border-[color:var(--brand)] hover:bg-[var(--list-hover)] disabled:opacity-50"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" />
        </svg>
        名前変更
      </button>
      <button
        type="button"
        onClick={onDelete}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--danger)]/50 px-3 py-1.5 text-sm text-[color:var(--danger)] transition hover:bg-[color:var(--danger)]/10 disabled:opacity-50"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
          <path d="M10 11v6M14 11v6" />
        </svg>
        削除
      </button>
    </>
  );
}
