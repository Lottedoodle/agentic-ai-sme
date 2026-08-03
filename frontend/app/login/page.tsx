"use client";

import { LoginForm } from "@/components/login-form";
import { useAuth } from "@/contexts/auth-context";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function LoginPage() {
  const { session, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && session) {
      router.replace("/chat");
    }
  }, [loading, session, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#e2eaf2] text-slate-400">
        กำลังโหลด...
      </div>
    );
  }

  if (session) {
    return null;
  }

  return <LoginForm />;
}
