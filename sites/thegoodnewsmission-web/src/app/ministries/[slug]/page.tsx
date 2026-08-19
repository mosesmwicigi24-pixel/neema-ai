import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import { PageHero } from "@/components/ui";
import { getMinistry, ministries } from "@/content/ministries";

type Params = { params: Promise<{ slug: string }> };

export function generateStaticParams() {
  return ministries.map((m) => ({ slug: m.slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const ministry = getMinistry(slug);
  if (!ministry) return { title: "Ministry not found" };
  return { title: ministry.name, description: ministry.summary };
}

export default async function MinistryPage({ params }: Params) {
  const { slug } = await params;
  const ministry = getMinistry(slug);
  if (!ministry) notFound();

  return (
    <>
      <PageHero title={ministry.name} subtitle={ministry.summary} />
      <article className="mx-auto max-w-3xl px-6 py-16">
        {ministry.leader && (
          <p className="text-sm font-bold uppercase tracking-wider text-brand-700">
            Led by {ministry.leader}
          </p>
        )}
        {ministry.body.map((p, i) => (
          <p key={i} className="mt-4 leading-relaxed text-ink-700">
            {p}
          </p>
        ))}
        <Link
          href="/ministries"
          className="mt-10 inline-block font-bold text-brand-600 hover:text-brand-700"
        >
          ← All ministries
        </Link>
      </article>
    </>
  );
}
