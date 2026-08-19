import type { Metadata } from "next";
import { EmptyState, PageHero } from "@/components/ui";

export const metadata: Metadata = { title: "Announcements" };

export default function AnnouncementsPage() {
  return (
    <>
      <PageHero
        title="Announcements"
        subtitle="Notices for the church family — service changes, meetings and news."
      />
      <EmptyState
        title="No announcements yet"
        message="Announcements will appear here once they are added. Create src/content/announcements.ts following the shape used by src/content/events.ts, then render it on this page."
      />
    </>
  );
}
