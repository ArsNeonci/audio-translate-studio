import type { Metadata } from "next";
import "@audio/ui/styles/base.css";
import "./globals.css";
import "@audio/ui/styles/dark-tokens.css";
import "./dark.css";
import { LanguageProvider } from "@/lib/i18n/language-context";
import { ThemeProvider, themeBootstrap } from "@audio/ui";

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
