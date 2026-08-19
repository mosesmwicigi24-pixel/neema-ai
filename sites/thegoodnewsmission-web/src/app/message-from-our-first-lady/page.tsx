import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { firstLadyMessagePage } from "@/content/pages";

export const metadata: Metadata = { title: "Message From Our First Lady" };

export default function Page() {
  return (
    <>
      <PageHero title={firstLadyMessagePage.title} subtitle={firstLadyMessagePage.intro} />
      <StaticPageBody page={firstLadyMessagePage} />
    </>
  );
}
