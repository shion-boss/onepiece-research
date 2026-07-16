"use client";

import { useEffect, useState } from "react";
import { useUser } from "@clerk/nextjs";
import { CLERK_ENABLED, DEV_GUEST_COOKIE } from "./auth";

function readGuestCookie(): boolean {
  if (typeof document === "undefined") return false;
  return new RegExp(`(?:^|; )${DEV_GUEST_COOKIE}=1(?:;|$)`).test(document.cookie);
}

// dev/QA 用: `onepiece_dev_guest` cookie でゲスト UI を強制 (= backend の実 auth には影響せず、
// 自分の UI をロック表示にするだけ)。 Clerk 有効な dev でもゲスト状態を検証できるようにする。
function useForcedGuest(): boolean {
  const [g, setG] = useState(false);
  useEffect(() => {
    setG(readGuestCookie());
    const h = () => setG(readGuestCookie());
    window.addEventListener("optcg-dev-guest-change", h);
    return () => window.removeEventListener("optcg-dev-guest-change", h);
  }, []);
  return g;
}

/**
 * 統一「ゲスト(未ログイン)判定」フック。
 * - 本番/Clerk 有効: useUser().isSignedIn で判定 (未ログイン = ゲスト)。 hydration 中は false。
 * - どのモードでも: dev-guest cookie が立っていれば強制ゲスト (= QA/検証用)。
 * useForcedGuest は常に呼ぶので hook 順は安定。 useUser は CLERK_ENABLED (build 定数) 時のみ。
 */
export function useIsGuest(): boolean {
  const forced = useForcedGuest();
  // 本番ビルド (= Clerk が実際に機能する) でのみ Clerk の未ログインをゲスト扱いに。
  // dev では明示トグル時のみゲスト (= Clerk 未 sign-in で誤ってロックしない = Track C 未完でも
  // 開発体験を壊さない)。 NODE_ENV/CLERK_ENABLED は build 定数なので hook 順は安定。
  if (CLERK_ENABLED && process.env.NODE_ENV === "production") {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { isSignedIn, isLoaded } = useUser();
    return forced || (isLoaded ? !isSignedIn : false);
  }
  return forced;
}
