"use client";

import { useEffect } from "react";
import { SessionProvider, useSession } from "next-auth/react";
import { federatedSignOut } from "@/lib/auth-client";

function AuthFailureGuard({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();

  useEffect(() => {
    if (session?.error === "RefreshTokenError") {
      void federatedSignOut();
    }
  }, [session?.error]);

  return children;
}

export default function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={5 * 60} refetchOnWindowFocus>
      <AuthFailureGuard>{children}</AuthFailureGuard>
    </SessionProvider>
  );
}
