import { SignUp } from "@clerk/nextjs";

// Clerk のホスト型サインアップ (= アカウント作成)。 dev (Clerk 未設定) では案内のみ。
export default function SignUpPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return (
      <div className="p-8 text-sm text-zinc-500 dark:text-zinc-400">
        開発モードではアカウント作成不要です (Clerk 未設定)。
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <SignUp />
    </div>
  );
}
