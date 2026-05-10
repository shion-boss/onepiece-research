"use client";

import { useState } from "react";
import { cardImageUrl, cardImageRemoteUrl } from "@/lib/images";

export function CardImage({
  cardId,
  alt,
  className,
  loading = "lazy",
}: {
  cardId: string;
  alt: string;
  className?: string;
  loading?: "lazy" | "eager";
}) {
  // cardId が切り替わったら errored をリセット (React 公式の prop→state 同期パターン)。
  // useEffect だと 1 フレーム古い画像が表示されるためレンダ中に同期する。
  const [errored, setErrored] = useState(false);
  const [prevCardId, setPrevCardId] = useState(cardId);
  if (cardId !== prevCardId) {
    setPrevCardId(cardId);
    setErrored(false);
  }
  const src = errored ? cardImageRemoteUrl(cardId) : cardImageUrl(cardId);
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      className={className}
      loading={loading}
      onError={() => {
        if (!errored) setErrored(true);
      }}
    />
  );
}
