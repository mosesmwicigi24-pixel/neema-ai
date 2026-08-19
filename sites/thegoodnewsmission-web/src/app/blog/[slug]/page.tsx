import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import { PageHero } from "@/components/ui";
import { getPost, posts } from "@/content/posts";
import { formatDate } from "@/lib/utils";

type Params = { params: Promise<{ slug: string }> };

export function generateStaticParams() {
  return posts.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) return { title: "Article not found" };
  return { title: post.title, description: post.excerpt };
}

export default async function PostPage({ params }: Params) {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) notFound();

  return (
    <>
      <PageHero title={post.title} />
      <article className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-sm text-ink-700">
          By {post.author} ·{" "}
          <time dateTime={post.date}>{formatDate(post.date)}</time>
        </p>
        {post.body.map((p, i) => (
          <p key={i} className="mt-4 leading-relaxed text-ink-700">
            {p}
          </p>
        ))}
        <Link
          href="/blog"
          className="mt-10 inline-block font-bold text-brand-600 hover:text-brand-700"
        >
          ← All articles
        </Link>
      </article>
    </>
  );
}
