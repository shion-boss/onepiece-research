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
  const [src, setSrc] = useState(cardImageUrl(cardId));
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      className={className}
      loading={loading}
      onError={() => {
        const remote = cardImageRemoteUrl(cardId);
        if (src !== remote) setSrc(remote);
      }}
    />
  );
}
