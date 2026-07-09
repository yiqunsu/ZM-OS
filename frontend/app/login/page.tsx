"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const res = await signIn("credentials", { email, password, redirect: false });
    setLoading(false);
    if (res?.error) {
      setError("邮箱或密码错误");
      return;
    }
    window.location.href = "/";
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm bg-white rounded-xl border border-slate-200 shadow-sm p-8 space-y-5"
      >
        <div>
          <h1 className="text-lg font-semibold text-slate-800">FilmOS 登录</h1>
          <p className="text-sm text-slate-500 mt-1">工厂订单管理系统</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="email" className="text-slate-700 text-sm font-medium">邮箱</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-slate-700 text-sm font-medium">密码</Label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
            required
          />
        </div>

        {error && (
          <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">{error}</p>
        )}

        <Button type="submit" disabled={loading} className="w-full bg-blue-600 hover:bg-blue-700 text-white">
          {loading ? "登录中…" : "登录"}
        </Button>
      </form>
    </div>
  );
}
