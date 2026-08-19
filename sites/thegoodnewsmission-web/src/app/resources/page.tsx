import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { resourcesPage } from "@/content/pages";

export const metadata: Metadata = { title: "Resources" };

export default function Page() {
  return (
    <>
      <PageHero title={resourcesPage.title} subtitle={resourcesPage.intro} />
      <StaticPageBody page={resourcesPage} />
    </>
  );
}
