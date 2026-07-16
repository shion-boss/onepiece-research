"use client";

import { useUser } from "@clerk/nextjs";
import { CLERK_ENABLED } from "./auth";

/**
 * ゲスト(未ログイン)判定。 Clerk の実ログイン状態で決める (dev/本番とも同じ)。
 * - Clerk 有効: 未ログイン = ゲスト。 hydration 中 (isLoaded=false) は false 扱い。
 * - Clerk 無効 (認証なしの bare dev): ゲスト概念なし → 常に false。
 * CLERK_ENABLED は build 定数なので分岐は安全 (AuthControls と同パターン)。
 */
export function useIsGuest(): boolean {
  if (!CLERK_ENABLED) return false;
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { isSignedIn, isLoaded } = useUser();
  return isLoaded ? !isSignedIn : false;
}
