"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Loader2, ShoppingBag, Sparkles } from "lucide-react";

import { useAuth } from "@/contexts/auth-context";

export function LoginForm() {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setSubmitting(true);

    const result =
      mode === "signin"
        ? await signIn(email.trim(), password)
        : await signUp(email.trim(), password);

    setSubmitting(false);

    if (result.error) {
      setError(result.error);
      return;
    }

    if (mode === "signup") {
      setInfo("สมัครสมาชิกสำเร็จ — ตรวจสอบอีเมลหรือลองเข้าสู่ระบบ");
      setMode("signin");
      return;
    }

    router.replace("/chat");
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-[#dce7f1] via-[#e2eaf2] to-[#d8e5f0] px-4">
      {/* decorative blobs */}
      <div className="pointer-events-none absolute -top-32 -left-32 h-96 w-96 rounded-full bg-sky-200/50 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-blue-200/50 blur-3xl" />

      <div className="relative w-full max-w-md rounded-3xl border border-[#cfdde9] bg-[#f4f8fc]/95 p-8 shadow-xl shadow-sky-200/40 backdrop-blur">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-400 to-blue-500 text-white shadow-lg shadow-sky-300/50">
            <ShoppingBag className="h-7 w-7" />
          </div>
          <h1 className="text-2xl font-bold text-slate-800">ShopMate AI</h1>
          <p className="flex items-center gap-1.5 text-sm text-slate-500">
            <Sparkles className="h-3.5 w-3.5 text-sky-500" />
            ผู้ช่วยตอบคำถามลูกค้าสำหรับร้านค้าออนไลน์
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-sm font-medium text-slate-600"
            >
              อีเมล
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border border-[#cfdde9] bg-white/70 px-4 py-3 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-sky-300 focus:ring-4 focus:ring-sky-100"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1.5 block text-sm font-medium text-slate-600"
            >
              รหัสผ่าน
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={6}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-[#cfdde9] bg-white/70 px-4 py-3 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-sky-300 focus:ring-4 focus:ring-sky-100"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-600">
              {error}
            </p>
          )}
          {info && (
            <p className="rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm text-emerald-600">
              {info}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-sky-400 to-blue-500 py-3 font-semibold text-white shadow-lg shadow-sky-200/70 transition hover:from-sky-300 hover:to-blue-400 disabled:opacity-60"
          >
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {mode === "signin" ? "เข้าสู่ระบบ" : "สมัครสมาชิก"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          {mode === "signin" ? "ยังไม่มีบัญชี?" : "มีบัญชีแล้ว?"}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setInfo(null);
            }}
            className="font-medium text-sky-600 hover:underline"
          >
            {mode === "signin" ? "สมัครสมาชิก" : "เข้าสู่ระบบ"}
          </button>
        </p>
      </div>
    </div>
  );
}
