// マルチユーザー化 P3: サーバコンポーネント用の認証ヘッダ。
// クライアントは authHeaders() (cookie を document から読む) を使うが、 サーバコンポーネントは
// next/headers の cookies() から読んで API fetch に明示的に渡す。
// 本番 Clerk では auth() / currentUser() からトークンを取って Authorization に差し替える。
import { cookies } from "next/headers";
import { DEV_USER_COOKIE, DEV_DEFAULT_USER } from "./auth";

export async function serverAuthHeaders(): Promise<Record<string, string>> {
  const store = await cookies();
  const user = store.get(DEV_USER_COOKIE)?.value || DEV_DEFAULT_USER;
  return { "X-Dev-User": user };
}
