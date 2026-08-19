import Link from "next/link";
import { cn } from "@/lib/utils";
import type { StaticPage } from "@/content/pages";

/** Banner at the top of every inner page. */
export function PageHero({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <section className="bg-ink-900 bg-[radial-gradient(ellipse_at_top_right,rgba(28,36,255,0.35),transparent_60%)]">
      <div className="mx-auto max-w-7xl px-6 py-16 sm:py-20">
        <h1 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-slate-300">
            {subtitle}
          </p>
        )}
      </div>
    </section>
  );
}

/** Centred heading used above home page sections. */
export function SectionHeading({
  eyebrow,
  title,
  className,
}: {
  eyebrow?: string;
  title: string;
  className?: string;
}) {
  return (
    <div className={cn("text-center", className)}>
      {eyebrow && (
        <p className="font-display text-lg text-brand-600">{eyebrow}</p>
      )}
      <h2 className="mt-1 text-2xl font-extrabold tracking-tight text-ink-900 sm:text-3xl">
        {title}
      </h2>
      <span className="mx-auto mt-4 block h-1 w-16 rounded-full bg-accent-500" />
    </div>
  );
}

/** Pull-quote for scripture. */
export function Scripture({
  reference,
  children,
}: {
  reference: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="mx-auto max-w-3xl text-center">
      <blockquote className="font-display text-xl leading-relaxed text-white sm:text-2xl">
        “{children}”
      </blockquote>
      <figcaption className="mt-4 text-sm font-bold uppercase tracking-widest text-brand-300">
        {reference}
      </figcaption>
    </figure>
  );
}

export function Button({
  href,
  children,
  variant = "primary",
  external,
}: {
  href: string;
  children: React.ReactNode;
  variant?: "primary" | "accent" | "outline";
  external?: boolean;
}) {
  const classes = cn(
    "inline-block rounded-full px-6 py-3 text-sm font-bold transition-colors",
    variant === "primary" && "bg-brand-600 text-white hover:bg-brand-700",
    variant === "accent" && "bg-accent-500 text-white hover:bg-accent-600",
    variant === "outline" &&
      "border-2 border-white text-white hover:bg-white hover:text-ink-900",
  );

  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={classes}
      >
        {children}
      </a>
    );
  }

  return (
    <Link href={href} className={classes}>
      {children}
    </Link>
  );
}

/** Renders a StaticPage from src/content/pages.ts as article prose. */
export function StaticPageBody({ page }: { page: StaticPage }) {
  return (
    <article className="mx-auto max-w-3xl px-6 py-16">
      {page.sections.map((section, i) => (
        <section key={i} className={i > 0 ? "mt-12" : undefined}>
          {section.heading && (
            <h2 className="text-xl font-extrabold tracking-tight text-ink-900 sm:text-2xl">
              {section.heading}
            </h2>
          )}
          {section.paragraphs?.map((p, j) => (
            <p key={j} className="mt-4 leading-relaxed text-ink-700">
              {p}
            </p>
          ))}
          {section.bullets && (
            <ul className="mt-4 space-y-3">
              {section.bullets.map((b, j) => (
                <li key={j} className="flex gap-3 leading-relaxed text-ink-700">
                  <span
                    className="mt-2 size-1.5 shrink-0 rounded-full bg-brand-600"
                    aria-hidden
                  />
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </article>
  );
}

/** Placeholder for pages whose content has not been supplied yet. */
export function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <h2 className="text-xl font-bold text-ink-900">{title}</h2>
      <p className="mt-3 leading-relaxed text-ink-700">{message}</p>
    </div>
  );
}
