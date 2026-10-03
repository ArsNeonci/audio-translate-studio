import type { Metadata } from "next";
import "./globals.css";
import "./dark.css";
import { LanguageProvider } from "@/lib/language-context";
import { ThemeProvider } from "@/lib/theme-context";
import { themeBootstrap } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Audio Studio",
  description: "Chinese transcription, Vietnamese translation, replacement rules and Vietnamese voice",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
        <ThemeProvider><LanguageProvider>{children}</LanguageProvider></ThemeProvider>
      </body>
    </html>
  );
}
