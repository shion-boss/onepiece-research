// マルチユーザー化 P3: サーバコンポーネント用の認証ヘッダ。
// クライアントは authHeaders() (cookie を document から読む) を使うが、 サーバコンポーネントは
// next/headers の cookies() から読んで API fetch に明示的に渡す。
// 本番 Clerk では auth() / currentUser() からトークンを取って Authorization に差し替える。
import { cookies } from "next/headers";
import { CLERK_ENABLED, DEV_USER_COOKIE, DEV_DEFAULT_USER, DEV_GUEST_COOKIE } from "./auth";

export async function serverAuthHeaders(): Promise<Record<string, string>> {
  if (CLERK_ENABLED) {
    // Clerk: server 側で session token を取り Bearer に。 未ログインは空 (= API が meta 限定/401)。
    const { auth } = await import("@clerk/nextjs/server");
    const { getToken } = await auth();
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  const store = await cookies();
  // dev: ゲスト擬似 (= 未ログイン扱い)。 X-Dev-Guest で backend が None(ゲスト)に。
  if (store.get(DEV_GUEST_COOKIE)?.value === "1") {
    return { "X-Dev-Guest": "1" };
  }
  const user = store.get(DEV_USER_COOKIE)?.value || DEV_DEFAULT_USER;
  return { "X-Dev-User": user };
}
