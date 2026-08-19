import type { Metadata } from "next";
import { PageHero } from "@/components/ui";
import { PostCard } from "@/components/cards";
import { posts } from "@/content/posts";
import { byDateDesc } from "@/lib/utils";

export const metadata: Metadata = { title: "Blog" };

export default function BlogPage() {
  return (
    <>
      <PageHero
        title="Blog"
        subtitle="Reflections, teaching and testimonies from The Good News Mission."
      />
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {byDateDesc(posts).map((p) => (
            <PostCard key={p.slug} post={p} />
          ))}
        </div>
      </div>
    </>
  );
}
