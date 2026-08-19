import type { Metadata } from "next";
import { PageHero, StaticPageBody } from "@/components/ui";
import { strategicPlanPage } from "@/content/pages";

export const metadata: Metadata = { title: "Our Strategic Plan" };

export default function Page() {
  return (
    <>
      <PageHero title={strategicPlanPage.title} subtitle={strategicPlanPage.intro} />
      <StaticPageBody page={strategicPlanPage} />
    </>
  );
}
