"use client";

import { useIsGuest } from "@/lib/useIsGuest";
import { LoginButton, LockIcon } from "./LoginButton";

// ログイン必須機能のページ全体ゲート。 ゲストには「ログインで使用可能」画面を出し、
// 子 (= 実機能) を mount させない (= 直 URL でも開始できない)。 ログイン済みは素通し。
export function LoginRequired({
  feature,
  children,
}: {
  feature: string;
  children: React.ReactNode;
}) {
  const isGuest = useIsGuest();
  if (!isGuest) return <>{children}</>;
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] px-6 py-12 text-center">
      <span
        className="flex h-14 w-14 items-center justify-center rounded-full"
        style={{ background: "var(--surface-3)", color: "var(--warning)" }}
      >
        <LockIcon size={26} />
      </span>
      <h2 className="text-lg font-semibold text-[color:var(--text-strong)]">
        {feature} はログインが必要です
      </h2>
      <p className="text-sm leading-relaxed text-[color:var(--text-muted)]">
        ログイン（無料）すると使用できます。 未ログインでは 人間 vs AI（環境デッキ）と
        カード・ルール閲覧をお使いいただけます。
      </p>
      <LoginButton className="inline-flex items-center gap-1.5 rounded-[var(--radius)] bg-[color:var(--brand)] px-5 py-2 text-sm font-semibold text-white transition hover:brightness-110">
        ログイン / 新規登録
      </LoginButton>
    </div>
  );
}
