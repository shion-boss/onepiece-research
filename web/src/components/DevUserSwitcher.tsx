"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getDevUser, setDevUser, isDevGuest, setDevGuest } from "@/lib/auth";

// 開発用ユーザー切替 (= マルチユーザー P3、 Clerk 未配線時のローカル検証用)。
// 本番では <ClerkProvider> + <UserButton> に置き換える (= この compose 位置に差し込む)。
export function DevUserSwitcher() {
  const router = useRouter();
  const [user, setUser] = useState<string>("local");
  const [guest, setGuest] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setUser(getDevUser());
    setGuest(isDevGuest());
  }, []);

  const apply = (id: string) => {
    const v = id.trim() || "local";
    setDevUser(v);
    setUser(v);
    setEditing(false);
    router.refresh(); // SSR(デッキ一覧)を新ユーザーで再取得
  };

  const toggleGuest = () => {
    const next = !guest;
    setDevGuest(next);
    setGuest(next);
    window.location.reload(); // auth ヘッダが変わるので全再取得
  };

  return (
    <div className="flex items-center gap-1.5 text-xs">
      {/* 開発用: ゲスト(未ログイン)擬似トグル。 本番は Clerk 未ログインで判定。 */}
      <button
        type="button"
        onClick={toggleGuest}
        className={`rounded-[var(--radius-sm)] border px-1.5 py-0.5 ${
          guest
            ? "border-[color:var(--warning)] text-[color:var(--warning)]"
            : "border-[color:var(--border-2)] text-[color:var(--text-muted)] hover:bg-[var(--list-hover)]"
        }`}
        title="開発用: ゲスト(未ログイン)を擬似"
      >
        {guest ? "ゲスト中" : "ゲスト擬似"}
      </button>
      <span className="text-[color:var(--text-muted)]" title="開発用: 本番では Clerk ログインに置換">
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
          className="w-24 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-1.5 py-0.5 text-[color:var(--text-default)] outline-none focus:border-[color:var(--brand)]"
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setDraft(user);
            setEditing(true);
          }}
          className="rounded-[var(--radius-sm)] border border-[color:var(--border-2)] px-1.5 py-0.5 font-mono text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
          title="クリックで開発ユーザーを切替"
        >
          {user}
        </button>
      )}
    </div>
  );
}
