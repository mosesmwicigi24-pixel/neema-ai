import type { Metadata } from "next";
import { PageHero } from "@/components/ui";
import { EventCard } from "@/components/cards";
import { events } from "@/content/events";
import { byDateDesc } from "@/lib/utils";

export const metadata: Metadata = { title: "Events" };

export default function EventsPage() {
  const today = new Date().toISOString().slice(0, 10);
  const sorted = byDateDesc(events);
  const upcoming = sorted.filter((e) => e.date >= today).reverse();
  const past = sorted.filter((e) => e.date < today);

  return (
    <>
      <PageHero
        title="Events"
        subtitle="Worship experiences, outreaches and gatherings. Everyone is welcome."
      />
      <div className="mx-auto max-w-7xl px-6 py-16">
        {upcoming.length > 0 && (
          <section>
            <h2 className="text-xl font-extrabold tracking-tight text-ink-900">
              Upcoming
            </h2>
            <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {upcoming.map((e) => (
                <EventCard key={e.slug} event={e} />
              ))}
            </div>
          </section>
        )}

        {past.length > 0 && (
          <section className={upcoming.length > 0 ? "mt-16" : undefined}>
            <h2 className="text-xl font-extrabold tracking-tight text-ink-900">
              Past events
            </h2>
            <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {past.map((e) => (
                <EventCard key={e.slug} event={e} />
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
