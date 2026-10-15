import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import AuthBar from "@/components/AuthBar";

export const metadata: Metadata = { title: "刺繡工作室", description: "上傳 SVG、PNG 或 JPG，產生可出廠的 DST/PES 刺繡檔" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-TW">
      <body className="min-h-screen">
        <header className="border-b border-line bg-panel">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <Link href="/studio" className="text-lg font-semibold tracking-wide">刺繡工作室 <span className="text-sm font-normal text-muted">MVP</span></Link>
            <AuthBar />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
