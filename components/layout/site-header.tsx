"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useLanguage } from "@/lib/i18n/language-context";
import ModelBanner from "@/components/layout/model-banner";
import QuitButton from "@/components/layout/quit-button";

export default function SiteHeader() {
  const { t, tr } = useLanguage();
  const pathname = usePathname();

  const navLinks = [
    { href: "/", label: t.nav.studio },
    { href: "/history", label: t.nav.history },
    { href: "/tools", label: t.nav.tools },
    { href: "/reprocess", label: t.nav.reprocess },
    { href: "/rules", label: t.nav.rules },
    { href: "/settings", label: t.nav.settings },
    { href: "/license", label: t.nav.license },
  ];

  return (
    <>
    <header className="header">
      <Link href="/" className="brand" aria-label={tr("Audio Studio Home")}>
        <Image
          src="/arsneonci-logo.png"
          alt="Ars Neonci Logo"
          width={36}
          height={36}
          className="brand-logo"
          priority
        />
        <span>Audio Studio</span>
      </Link>
      <nav aria-label={tr("Main navigation")} className="site-nav">
        {navLinks.map((link) => {
          const isActive = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={isActive ? "active" : undefined}
              aria-current={isActive ? "page" : undefined}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      <QuitButton />
    </header>
    <ModelBanner />
    </>
  );
}
