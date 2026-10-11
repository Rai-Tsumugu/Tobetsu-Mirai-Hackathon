import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "当別未来フェス | チームWebアプリ",
  description: "当別の課題を解決するハッカソンチームのWebアプリです。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
