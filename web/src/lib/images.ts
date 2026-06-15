export function cardImageUrl(cardId: string): string {
  return `/cards/${encodeURIComponent(cardId)}.png`;
}

// fallback: 公式 CDN は `cross-origin-resource-policy: same-site` ヘッダー付きで、
// 別ドメイン (= *.vercel.app) からの img embed が ブラウザによって blocked される。
// API project の proxy 経由 (= 同一オリジン扱い) で取得して制限を回避 + Vercel edge
// cache を効かせる。 NEXT_PUBLIC_API_BASE 未設定時 (= 開発時) は 直接 公式 CDN を使う。
export function cardImageRemoteUrl(cardId: string): string {
  // 公式 CDN は cross-origin-resource-policy: same-site なので、 別オリジン
  // (localhost:3000 / *.vercel.app) からの直 embed はブラウザにブロックされる。
  // 必ず API プロキシ (= 同一サイト扱い + CORP 除去) 経由にする。 dev でも
  // api.ts と同じく localhost:8000 を既定にして、 未キャッシュ画像が dev でも出るように。
  const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
  return `${apiBase}/api/cards/${encodeURIComponent(cardId)}/image`;
}
