"use client";

import { CLERK_ENABLED } from "@/lib/auth";
import { DevUserSwitcher } from "./DevUserSwitcher";
import { SignInButton, UserButton, useUser } from "@clerk/nextjs";

// 認証コントロール。 Clerk 有効時は UserButton / ログインボタン、 dev では開発ユーザー切替。
// dev では ClerkControls (= useUser を呼ぶ) を一切描画しないので ClerkProvider 不在でも安全。
export function AuthControls() {
  if (!CLERK_ENABLED) return <DevUserSwitcher />;
  return <ClerkControls />;
}

function ClerkControls() {
  const { isSignedIn, isLoaded } = useUser();
  if (!isLoaded) return <div className="h-9 w-9" />;
  // ログイン中: アバター (UserButton)。 アクティビティバーに収まるアイコン。
  if (isSignedIn) return <UserButton />;
  // 未ログイン: アカウントアイコン (クリックで Clerk のログイン/登録モーダル)。
  return (
    <SignInButton mode="modal">
      <button
        type="button"
        title="ログイン / 新規登録"
        aria-label="ログイン / 新規登録"
        className="flex h-9 w-9 items-center justify-center rounded-md text-[color:var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-white"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7">
          <circle cx="12" cy="8" r="4" />
          <path d="M5 20a7 7 0 0 1 14 0" strokeLinecap="round" />
        </svg>
      </button>
    </SignInButton>
  );
}
