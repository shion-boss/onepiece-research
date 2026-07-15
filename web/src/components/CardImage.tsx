"use client";

import { useState } from "react";
import { cardImageUrl, cardImageRemoteUrl } from "@/lib/images";

export function CardImage({
  cardId,
  alt,
  className,
  loading = "lazy",
  style,
  remoteFirst = false,
}: {
  cardId: string;
  alt: string;
  className?: string;
  loading?: "lazy" | "eager";
  style?: React.CSSProperties;
  // remoteFirst: 最初から API プロキシ URL を src にする (= ローカル /cards/*.png が無い
  // 本番で「404 → onError → 差し替え」の 1 往復に頼らず確実に表示する)。 陣取り盤の
  // crop 表示は絶対配置 + lazy で fallback が発火しにくいので盤では true にする。
  remoteFirst?: boolean;
}) {
  // cardId が切り替わったら errored をリセット (React 公式の prop→state 同期パターン)。
  // useEffect だと 1 フレーム古い画像が表示されるためレンダ中に同期する。
  const [errored, setErrored] = useState(false);
  const [prevCardId, setPrevCardId] = useState(cardId);
  if (cardId !== prevCardId) {
    setPrevCardId(cardId);
    setErrored(false);
  }
  // 既定 = ローカル優先 → 失敗でプロキシ。 remoteFirst = プロキシ優先 → 失敗でローカル。
  const primary = remoteFirst ? cardImageRemoteUrl(cardId) : cardImageUrl(cardId);
  const fallback = remoteFirst ? cardImageUrl(cardId) : cardImageRemoteUrl(cardId);
  const src = errored ? fallback : primary;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      className={className}
      style={style}
      loading={loading}
      onError={() => {
        if (!errored) setErrored(true);
      }}
    />
  );
}
