import Link from "next/link";
import { CalendarDays, MapPin, Mic } from "lucide-react";
import { formatDate } from "@/lib/utils";
import type { Ministry } from "@/content/ministries";
import type { ChurchEvent } from "@/content/events";
import type { Sermon } from "@/content/sermons";
import type { Post } from "@/content/posts";

const cardBase =
  "flex h-full flex-col rounded-xl border border-slate-200 bg-white p-6 transition-shadow hover:shadow-lg";

export function MinistryCard({ ministry }: { ministry: Ministry }) {
  return (
    <article className={cardBase}>
      <h3 className="text-lg font-bold text-ink-900">
        <Link
          href={`/ministries/${ministry.slug}`}
          className="hover:text-brand-700"
        >
          {ministry.name}
        </Link>
      </h3>
      <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-700">
        {ministry.summary}
      </p>
      <Link
        href={`/ministries/${ministry.slug}`}
        className="mt-4 text-sm font-bold text-brand-600 hover:text-brand-700"
      >
        Read more →
      </Link>
    </article>
  );
}

export function EventCard({ event }: { event: ChurchEvent }) {
  return (
    <article className={cardBase}>
      <h3 className="text-lg font-bold text-ink-900">{event.title}</h3>
      <dl className="mt-3 space-y-1.5 text-sm text-ink-700">
        <div className="flex items-center gap-2">
          <CalendarDays className="size-4 shrink-0 text-brand-600" aria-hidden />
          <dt className="sr-only">Date</dt>
          <dd>
            <time dateTime={event.date}>{formatDate(event.date)}</time> ·{" "}
            {event.timeLabel}
          </dd>
        </div>
        <div className="flex items-center gap-2">
          <MapPin className="size-4 shrink-0 text-brand-600" aria-hidden />
          <dt className="sr-only">Location</dt>
          <dd>{event.location}</dd>
        </div>
      </dl>
      <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-700">
        {event.summary}
      </p>
    </article>
  );
}

export function SermonCard({ sermon }: { sermon: Sermon }) {
  return (
    <article className={cardBase}>
      <h3 className="text-lg font-bold text-ink-900">{sermon.title}</h3>
      <dl className="mt-3 space-y-1.5 text-sm text-ink-700">
        <div className="flex items-center gap-2">
          <Mic className="size-4 shrink-0 text-brand-600" aria-hidden />
          <dt className="sr-only">Speaker</dt>
          <dd>{sermon.speaker}</dd>
        </div>
        <div className="flex items-center gap-2">
          <CalendarDays className="size-4 shrink-0 text-brand-600" aria-hidden />
          <dt className="sr-only">Date</dt>
          <dd>
            <time dateTime={sermon.date}>{formatDate(sermon.date)}</time>
          </dd>
        </div>
      </dl>
      {sermon.scripture && (
        <p className="mt-3 font-display text-brand-700">{sermon.scripture}</p>
      )}
      <p className="mt-2 flex-1 text-sm leading-relaxed text-ink-700">
        {sermon.summary}
      </p>
    </article>
  );
}

export function PostCard({ post }: { post: Post }) {
  return (
    <article className={cardBase}>
      <p className="text-xs font-bold uppercase tracking-wider text-brand-600">
        <time dateTime={post.date}>{formatDate(post.date)}</time>
      </p>
      <h3 className="mt-2 text-lg font-bold text-ink-900">
        <Link href={`/blog/${post.slug}`} className="hover:text-brand-700">
          {post.title}
        </Link>
      </h3>
      <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-700">
        {post.excerpt}
      </p>
      <Link
        href={`/blog/${post.slug}`}
        className="mt-4 text-sm font-bold text-brand-600 hover:text-brand-700"
      >
        Continue reading →
      </Link>
    </article>
  );
}
