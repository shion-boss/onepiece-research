import { SignIn } from "@clerk/nextjs";

// Clerk のホスト型サインイン。 dev (Clerk 未設定) ではログイン不要なので案内のみ表示。
export default function SignInPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return (
      <div className="p-8 text-sm text-zinc-500 dark:text-zinc-400">
        開発モードではログイン不要です (Clerk 未設定)。
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <SignIn />
    </div>
  );
}
