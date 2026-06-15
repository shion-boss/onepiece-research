"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getDevUser, setDevUser } from "@/lib/auth";

// 開発用ユーザー切替 (= マルチユーザー P3、 Clerk 未配線時のローカル検証用)。
// 本番では <ClerkProvider> + <UserButton> に置き換える (= この compose 位置に差し込む)。
export function DevUserSwitcher() {
  const router = useRouter();
  const [user, setUser] = useState<string>("local");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setUser(getDevUser());
  }, []);

  const apply = (id: string) => {
    const v = id.trim() || "local";
    setDevUser(v);
    setUser(v);
    setEditing(false);
    router.refresh(); // SSR(デッキ一覧)を新ユーザーで再取得
  };

  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className="text-zinc-400" title="開発用: 本番では Clerk ログインに置換">
        user
      </span>
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") apply(draft);
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={() => setEditing(false)}
          placeholder={user}
          className="w-24 rounded border border-zinc-300 bg-white px-1.5 py-0.5 dark:border-zinc-700 dark:bg-zinc-900"
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setDraft(user);
            setEditing(true);
          }}
          className="rounded border border-zinc-300 px-1.5 py-0.5 font-mono text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          title="クリックで開発ユーザーを切替"
        >
          {user}
        </button>
      )}
    </div>
  );
}
