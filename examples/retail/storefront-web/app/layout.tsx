import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ACME",
  description: "和 ACME 助手一起逛 ACME 商品目录。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // 源码是 lang="en"；这里的界面文案是中文。
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
