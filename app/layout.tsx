import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Audio Studio · Chinese Transcript",
  description: "YouTube Chinese speech to transcript",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
