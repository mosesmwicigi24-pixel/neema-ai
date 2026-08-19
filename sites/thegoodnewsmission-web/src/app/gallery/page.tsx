import type { Metadata } from "next";
import { EmptyState, PageHero } from "@/components/ui";

export const metadata: Metadata = { title: "Gallery" };

export default function GalleryPage() {
  return (
    <>
      <PageHero
        title="Gallery"
        subtitle="Moments from our services, outreaches and events."
      />
      <EmptyState
        title="Photos coming soon"
        message="Add photographs to /public/gallery and list them in a src/content/gallery.ts file, then render them as a responsive grid here."
      />
    </>
  );
}
