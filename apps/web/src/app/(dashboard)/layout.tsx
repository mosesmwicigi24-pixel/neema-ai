import { auth } from '@/lib/auth';
import { redirect } from 'next/navigation';
import Link from 'next/link';
import {
  MessageSquare, Users, ShoppingCart, BookOpen,
  LayoutDashboard, LogOut
} from 'lucide-react';

const nav = [
  { href: '/dashboard',      label: 'Dashboard',      icon: LayoutDashboard },
  { href: '/conversations',  label: 'Conversations',   icon: MessageSquare },
  { href: '/agents',         label: 'Agents',          icon: Users },
  { href: '/orders',         label: 'Orders',          icon: ShoppingCart },
  { href: '/catalog',        label: 'Catalog',         icon: BookOpen },
];

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session) redirect('/login');

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100">
      {/* Sidebar */}
      <aside className="w-60 flex-shrink-0 border-r border-zinc-800 flex flex-col">
        <div className="p-5 border-b border-zinc-800">
          <h1 className="text-lg font-bold tracking-tight">
            Neema <span className="text-emerald-400">Admin</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">Bethany House</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {nav.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 px-3 py-2 rounded-md text-sm
                         text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800
                         transition-colors"
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="p-3 border-t border-zinc-800">
          <p className="text-xs text-zinc-500 px-3 mb-2">
            {session.user?.email}
          </p>
          <form action={async () => { 'use server'; /* signOut */ }}>
            <button
              type="submit"
              className="flex items-center gap-3 w-full px-3 py-2 rounded-md
                         text-sm text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
            >
              <LogOut className="w-4 h-4" />
              Sign out
            </button>
          </form>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}