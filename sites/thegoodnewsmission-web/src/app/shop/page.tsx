import type { Metadata } from "next";
import { EmptyState, PageHero } from "@/components/ui";

export const metadata: Metadata = { title: "Shop" };

export default function ShopPage() {
  return (
    <>
      <PageHero
        title="Shop"
        subtitle="Books, teaching materials and church merchandise."
      />
      <EmptyState
        title="The shop is not open yet"
        message="This page is a placeholder. Decide whether the shop should be a simple catalogue or a full checkout before building it out."
      />
    </>
  );
}
