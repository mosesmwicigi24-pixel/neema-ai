import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { statutesPage } from "@/content/pages";

export const metadata: Metadata = { title: "Our Statutes" };

export default function Page() {
  return (
    <>
      <PageHero title={statutesPage.title} subtitle={statutesPage.intro} />
      <StaticPageBody page={statutesPage} />
    </>
  );
}
