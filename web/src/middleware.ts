import { NextResponse, type NextRequest } from "next/server";
import { clerkMiddleware } from "@clerk/nextjs/server";

// Clerk 有効 (= publishable key が env にある) 時のみ clerkMiddleware を通し、 auth() / Clerk hooks
// を成立させる。 dev (キー無) は passthrough = 認証ミドルウェア無しで従来どおり動く。
const CLERK_ENABLED = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

const passthrough = (_req: NextRequest) => NextResponse.next();

export default CLERK_ENABLED ? clerkMiddleware() : passthrough;

export const config = {
  matcher: [
    // Next 内部・静的アセットを除外し、 それ以外の全ルートを通す (Clerk 標準 matcher)。
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpg|jpeg|gif|png|svg|ico|webp|woff2?|ttf|map)).*)",
    "/(api|trpc)(.*)",
  ],
};
