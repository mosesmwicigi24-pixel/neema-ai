import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { aboutPage } from "@/content/pages";

export const metadata: Metadata = { title: "About Us" };

export default function Page() {
  return (
    <>
      <PageHero title={aboutPage.title} subtitle={aboutPage.intro} />
      <StaticPageBody page={aboutPage} />
    </>
  );
}
