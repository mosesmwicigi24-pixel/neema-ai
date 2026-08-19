import Link from "next/link";
import { Mail, MapPin, Phone } from "lucide-react";
import { footerQuickLinks, site } from "@/content/site";
import { ministries } from "@/content/ministries";

export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="bg-ink-900 text-slate-300">
      <div className="mx-auto grid max-w-7xl gap-10 px-6 py-16 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-brand-600 font-display text-lg text-white">
              ✝
            </span>
            <span className="font-bold text-white">{site.name}</span>
          </div>
          <p className="mt-4 text-sm leading-relaxed">
            A missionary sending church. We desire to show the love of Christ to
            all people by sharing the Good News of our Lord Jesus Christ with
            every soul across the world.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            {site.socials.map((s) => (
              <a
                key={s.name}
                href={s.href}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full border border-white/20 px-3 py-1 text-xs hover:border-brand-400 hover:text-white"
              >
                {s.name}
              </a>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-white">
            Quick Links
          </h2>
          <ul className="mt-4 space-y-2 text-sm">
            {footerQuickLinks.map((l) => (
              <li key={l.href}>
                <Link href={l.href} className="hover:text-brand-300">
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-white">
            Our Ministries
          </h2>
          <ul className="mt-4 space-y-2 text-sm">
            {ministries.map((m) => (
              <li key={m.slug}>
                <Link
                  href={`/ministries/${m.slug}`}
                  className="hover:text-brand-300"
                >
                  {m.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-white">
            Contact Us
          </h2>
          <ul className="mt-4 space-y-3 text-sm">
            <li className="flex gap-3">
              <MapPin className="mt-0.5 size-4 shrink-0 text-brand-400" aria-hidden />
              <span>
                {site.contact.address}
                <br />
                {site.contact.city}
              </span>
            </li>
            <li className="flex gap-3">
              <Phone className="mt-0.5 size-4 shrink-0 text-brand-400" aria-hidden />
              <a href={site.contact.phoneHref} className="hover:text-brand-300">
                {site.contact.phone}
              </a>
            </li>
            <li className="flex gap-3">
              <Mail className="mt-0.5 size-4 shrink-0 text-brand-400" aria-hidden />
              <a
                href={`mailto:${site.contact.email}`}
                className="break-all hover:text-brand-300"
              >
                {site.contact.email}
              </a>
            </li>
          </ul>
        </div>
      </div>

      <div className="border-t border-white/10">
        <div className="mx-auto max-w-7xl px-6 py-6 text-center text-xs">
          &copy; {year} {site.name}. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
