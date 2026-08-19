import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { pastorMessagePage } from "@/content/pages";

export const metadata: Metadata = { title: "Message From Our Pastor" };

export default function Page() {
  return (
    <>
      <PageHero title={pastorMessagePage.title} subtitle={pastorMessagePage.intro} />
      <StaticPageBody page={pastorMessagePage} />
    </>
  );
}
