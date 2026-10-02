import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Audio Studio · Chinese to Vietnamese",
  description: "Chinese transcription, Vietnamese translation, replacement rules and Vietnamese voice",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
