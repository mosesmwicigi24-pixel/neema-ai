import type { Metadata } from "next";
import { PageHero } from "@/components/ui";
import { SermonCard } from "@/components/cards";
import { sermons } from "@/content/sermons";
import { byDateDesc } from "@/lib/utils";

export const metadata: Metadata = { title: "Sermons" };

export default function SermonsPage() {
  return (
    <>
      <PageHero
        title="Sermons"
        subtitle="Teaching from our Sunday gatherings. Listen, be encouraged, and share with someone who needs it."
      />
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {byDateDesc(sermons).map((s) => (
            <SermonCard key={s.slug} sermon={s} />
          ))}
        </div>
      </div>
    </>
  );
}
