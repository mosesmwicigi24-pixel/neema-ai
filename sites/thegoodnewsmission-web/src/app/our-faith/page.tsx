import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { faithPage } from "@/content/pages";

export const metadata: Metadata = { title: "Our Faith" };

export default function Page() {
  return (
    <>
      <PageHero title={faithPage.title} subtitle={faithPage.intro} />
      <StaticPageBody page={faithPage} />
    </>
  );
}
