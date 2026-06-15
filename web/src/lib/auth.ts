// マルチユーザー化 P3: フロント側の認証抽象 (docs/multiuser_plan.md)。
//
// 開発モード (= Clerk 未配線): `onepiece_dev_user` cookie で「現在のユーザー」を表し、
//   API には X-Dev-User ヘッダで送る。 cookie なのでクライアント/サーバ両方から読める。
//   → バックエンドの per-user 隔離 (api/auth.py の dev backend) をローカルUIで実体験できる。
// 本番モード (= Clerk): authHeaders() を `Authorization: Bearer <clerk token>` に差し替え、
//   <ClerkProvider> 配下で useAuth().getToken() を使う (= wire-and-go スロット)。

export const DEV_USER_COOKIE = "onepiece_dev_user";
export const DEV_DEFAULT_USER = "local";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
  return m ? decodeURIComponent(m[1]) : null;
}

/** 現在の dev ユーザー id (クライアント)。 cookie 未設定なら "local"。 */
export function getDevUser(): string {
  return readCookie(DEV_USER_COOKIE) || DEV_DEFAULT_USER;
}

/** dev ユーザーを切り替える (cookie 保存)。 呼び出し側でリロードして反映する。 */
export function setDevUser(id: string): void {
  if (typeof document === "undefined") return;
  const v = encodeURIComponent(id.trim() || DEV_DEFAULT_USER);
  document.cookie = `${DEV_USER_COOKIE}=${v}; path=/; max-age=31536000; samesite=lax`;
}

/**
 * API 呼び出しに付ける認証ヘッダ。 クライアントでのみ有効 (= document がある)。
 * サーバコンポーネントからは cookie を読んで明示的に渡す (= fetchDecks(extraHeaders))。
 * 本番 Clerk では Authorization: Bearer に差し替える (= ここが唯一の変更点)。
 */
export function authHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  return { "X-Dev-User": getDevUser() };
}
