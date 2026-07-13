import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { WorkspaceShell } from "@/components/WorkspaceShell";

// Clerk 有効 (= publishable key が env にある) 時のみ <ClerkProvider> で包む。
// dev (キー無) は provider 無しで従来どおり = ローカルは Clerk 不要。
const CLERK_ENABLED = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "One Piece Research",
  description: "ワンピースカードゲーム デッキ研究ツール",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const tree = (
    <html
      lang="ja"
      className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="h-screen overflow-hidden">
        <WorkspaceShell>{children}</WorkspaceShell>
      </body>
    </html>
  );
  return CLERK_ENABLED ? <ClerkProvider>{tree}</ClerkProvider> : tree;
}
