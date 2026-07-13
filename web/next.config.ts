import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // クライアントのルーターキャッシュを延長 = 開いたタブ (デッキ詳細等) に戻ると
  // サーバー往復なしで即表示 (VSCode 風「開いているタブは即開く」)。
  experimental: {
    staleTimes: {
      dynamic: 600, // 動的ページを 10 分クライアントキャッシュ
      static: 600,
    },
  },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "www.onepiece-cardgame.com" },
    ],
  },
};

export default nextConfig;
