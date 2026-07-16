"use client";

import { CLERK_ENABLED } from "@/lib/auth";
import { SignInButton } from "@clerk/nextjs";

// ログインを促すクリック要素。 ゲスト向けロック機能の CTA に使う。
// - 本番 (Clerk): クリックで Clerk のログイン/登録モーダル。
// - dev: /sign-in へ (= 開発ではログイン不要の旨を出すページ)。
// CLERK_ENABLED は build 時定数なので分岐は安全 (AuthControls と同パターン)。
export function LoginButton({
  children,
  className,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  if (CLERK_ENABLED) {
    return (
      <SignInButton mode="modal">
        <button type="button" className={className} title={title}>
          {children}
        </button>
      </SignInButton>
    );
  }
  return (
    <a href="/sign-in" className={className} title={title}>
      {children}
    </a>
  );
}

// 小さな鍵アイコン (= ロック表示用)。 絵文字禁止なので SVG。
export function LockIcon({ size = 12 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" strokeLinecap="round" />
    </svg>
  );
}
