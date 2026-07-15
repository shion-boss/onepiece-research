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
  if (!isLoaded) return <div className="h-7" />;
  if (isSignedIn) {
    return (
      <div className="flex items-center gap-2">
        <UserButton />
      </div>
    );
  }
  return (
    <SignInButton mode="modal">
      <button
        type="button"
        className="rounded-md px-2.5 py-1 text-xs font-medium text-white"
        style={{
          background:
            "linear-gradient(135deg, var(--brand-strong) 0%, var(--brand) 100%)",
        }}
      >
        ログイン
      </button>
    </SignInButton>
  );
}
