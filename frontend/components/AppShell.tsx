"use client";

import { usePathname } from "next/navigation";

/**
 * 包裹页面主体。登录页没有侧边栏 / 底部导航，
 * 因此不需要为它们预留偏移，否则内容会偏离视口中心。
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthRoute = pathname.startsWith("/login");

  if (isAuthRoute) {
    return <div className="min-h-screen flex flex-col">{children}</div>;
  }

  return (
    // 桌面端偏移左侧边栏，手机端底部留出导航栏空间
    <div className="md:ml-60 pb-16 md:pb-0 min-h-screen flex flex-col">
      {children}
    </div>
  );
}
