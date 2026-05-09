export function cardImageUrl(cardId: string): string {
  return `/cards/${encodeURIComponent(cardId)}.png`;
}

export function cardImageRemoteUrl(cardId: string): string {
  return `https://www.onepiece-cardgame.com/images/cardlist/card/${cardId}.png`;
}
