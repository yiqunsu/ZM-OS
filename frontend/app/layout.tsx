import type { Metadata, Viewport } from "next";
import ConfirmationProvider from "@/components/ConfirmationProvider";
import Sidebar from "@/components/Sidebar";
import AppShell from "@/components/AppShell";
import AuthSessionProvider from "@/components/AuthSessionProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "FilmOS · 智能排产工作台",
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
    <html lang="zh-CN" className="h-full">
      <body className="min-h-full bg-slate-50 text-slate-800 antialiased">
        <AuthSessionProvider>
          <ConfirmationProvider>
          <Sidebar />
          <AppShell>{children}</AppShell>
          </ConfirmationProvider>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
