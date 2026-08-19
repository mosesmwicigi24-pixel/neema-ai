import type { Metadata } from "next";
import { PageHero } from "@/components/ui";
import { MinistryCard } from "@/components/cards";
import { ministries } from "@/content/ministries";

export const metadata: Metadata = { title: "Ministries" };

export default function MinistriesPage() {
  return (
    <>
      <PageHero
        title="Our Ministries"
        subtitle="There is a place for you to serve, grow and belong. Every department exists to help people meet Christ and become who God made them to be."
      />
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {ministries.map((m) => (
            <MinistryCard key={m.slug} ministry={m} />
          ))}
        </div>
      </div>
    </>
  );
}
