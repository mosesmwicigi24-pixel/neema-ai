import type { Metadata } from "next";
import { EmptyState, PageHero } from "@/components/ui";

export const metadata: Metadata = { title: "Videos" };

export default function VideosPage() {
  return (
    <>
      <PageHero
        title="Videos"
        subtitle="Recorded services, worship experiences and teaching."
      />
      <EmptyState
        title="Videos coming soon"
        message="Add YouTube or Vimeo IDs to a src/content/videos.ts file and embed them here."
      />
    </>
  );
}
