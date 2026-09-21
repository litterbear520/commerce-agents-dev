import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ACME",
  description: "和 ACME 助手一起逛 ACME 商品目录。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
