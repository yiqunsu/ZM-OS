"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const AUTH_PROVIDER = process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? "local";

function LoginCard() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState("");
  const [loading, setLoading] = useState(false);
  const hasError = Boolean(searchParams.get("error")) || Boolean(localError);

  async function handleLocalLogin(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setLocalError("");
    const result = await signIn("credentials", { email, password, redirect: false });
    setLoading(false);
    if (result?.error) {
      setLocalError("邮箱或密码错误");
      return;
    }
    window.location.assign("/");
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <section className="w-full max-w-sm space-y-6 rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">FilmOS 登录</h1>
          <p className="mt-1 text-sm text-slate-500">使用统一工作区账号安全登录</p>
        </div>

        {hasError && (
          <p role="alert" className="rounded-md border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-500">
            {localError || "登录未完成，请确认账号已启用且只分配了一个 FilmOS 角色。"}
          </p>
        )}

        {AUTH_PROVIDER === "casdoor" ? (
          <Button
            type="button"
            onClick={() => signIn("casdoor", { redirectTo: "/" })}
            className="w-full bg-blue-600 text-white hover:bg-blue-700"
          >
            使用 Casdoor 登录
          </Button>
        ) : (
          <form onSubmit={handleLocalLogin} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 text-white hover:bg-blue-700"
            >
              {loading ? "登录中…" : "登录"}
            </Button>
          </form>
        )}

        <p className="text-center text-xs leading-5 text-slate-400">
          {AUTH_PROVIDER === "casdoor"
            ? "账号、密码和角色由 FilmOS 管理员统一维护"
            : "本地密码登录仅用于开发环境"}
        </p>
      </section>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginCard />
    </Suspense>
  );
}
