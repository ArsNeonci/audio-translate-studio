import Link from "next/link";

export default function SiteHeader() {
  return <header className="header"><Link href="/" className="brand"><span className="brand-icon">声</span>Audio Studio</Link><nav aria-label="Main navigation"><Link href="/">Studio</Link><Link href="/history">History</Link><Link href="/tools">Tools</Link><Link href="/reprocess">Reprocess</Link><Link href="/rules">Community Rules</Link><Link href="/settings">Settings</Link><Link href="/license">License</Link></nav></header>;
}
