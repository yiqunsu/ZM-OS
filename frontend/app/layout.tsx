import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import AuthSessionProvider from "@/components/AuthSessionProvider";
import "./globals.css";

const geist = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "订单管理系统",
  description: "塑料薄膜工厂订单管理",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#C8331F",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className={`${geist.variable} h-full`}>
      <body className="min-h-full bg-slate-50 text-slate-800 antialiased">
        <AuthSessionProvider>
          <Sidebar />
          {/* 桌面端偏移左侧边栏，手机端底部留出导航栏空间 */}
          <div className="md:ml-16 pb-16 md:pb-0 min-h-screen flex flex-col">
            {children}
          </div>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
