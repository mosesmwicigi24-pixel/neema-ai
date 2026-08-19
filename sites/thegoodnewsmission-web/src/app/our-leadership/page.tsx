import type { Metadata } from "next";
import { PageHero } from "@/components/ui";
import { leadership } from "@/content/leadership";

export const metadata: Metadata = { title: "Our Leadership" };

export default function LeadershipPage() {
  return (
    <>
      <PageHero
        title="Our Leadership"
        subtitle="The team God has entrusted with shepherding The Good News Mission."
      />
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {leadership.map((leader, i) => (
            <article
              key={`${leader.role}-${i}`}
              className="rounded-xl border border-slate-200 bg-white p-6"
            >
              <div
                className="grid size-16 place-items-center rounded-full bg-brand-50 font-display text-2xl text-brand-600"
                aria-hidden
              >
                {leader.name.charAt(0)}
              </div>
              <h2 className="mt-4 text-lg font-bold text-ink-900">
                {leader.name}
              </h2>
              <p className="mt-1 text-sm font-bold text-brand-700">
                {leader.role}
              </p>
              {leader.bio && (
                <p className="mt-3 text-sm leading-relaxed text-ink-700">
                  {leader.bio}
                </p>
              )}
            </article>
          ))}
        </div>
        <p className="mt-12 rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-ink-700">
          Names, photographs and biographies are placeholders. Update them in{" "}
          <code className="rounded bg-slate-100 px-1.5 py-0.5">
            src/content/leadership.ts
          </code>
          .
        </p>
      </div>
    </>
  );
}
