import Link from "next/link";
import { Button, Scripture, SectionHeading } from "@/components/ui";
import {
  EventCard,
  MinistryCard,
  PostCard,
  SermonCard,
} from "@/components/cards";
import { site } from "@/content/site";
import { ministries } from "@/content/ministries";
import { events } from "@/content/events";
import { sermons } from "@/content/sermons";
import { posts } from "@/content/posts";
import { sundayServices, weeklyServices } from "@/content/services";
import { byDateDesc } from "@/lib/utils";

export default function HomePage() {
  const latestEvents = byDateDesc(events).slice(0, 3);
  const latestSermon = byDateDesc(sermons)[0];
  const latestPosts = byDateDesc(posts).slice(0, 3);
  const andrewProject = ministries.find((m) => m.slug === "the-andrew-project");

  return (
    <>
      {/* Hero */}
      <section className="relative bg-ink-900 bg-[radial-gradient(ellipse_at_50%_-10%,rgba(28,36,255,0.45),transparent_65%)]">
        <div className="mx-auto max-w-7xl px-6 py-24 text-center sm:py-32">
          <p className="font-display text-xl text-brand-300">
            {site.tagline}
          </p>
          <h1 className="mt-4 text-4xl font-extrabold tracking-tight text-white sm:text-6xl">
            You&rsquo;re Welcome Here
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
            A dynamic, multicultural, missionary sending church in Nairobi.
            Join us every Sunday to celebrate Jesus and our faith in Him.
          </p>
          <div className="mt-10 flex flex-wrap justify-center gap-4">
            <Button href="/about-us">Plan Your Visit</Button>
            <Button href="/sermons" variant="outline">
              Listen to a Sermon
            </Button>
          </div>
        </div>
      </section>

      {/* Scripture */}
      <section className="bg-brand-700 py-16">
        <div className="mx-auto max-w-7xl px-6">
          <Scripture reference="John 8:12">
            I am the light of the world. If you follow me, you won&rsquo;t have
            to walk in darkness, because you will have the light that leads to
            life
          </Scripture>
        </div>
      </section>

      {/* Welcome */}
      <section className="py-20">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <SectionHeading
            eyebrow="Become new now!"
            title="You're Welcome Here; Where Everyone is Someone!"
          />
          <p className="mt-8 leading-relaxed text-ink-700">
            The Good News Mission is more than a church! It&rsquo;s a family of
            believers who have come together to share the love of God. Our
            immediate task is to help you become the person God made you to be.
            No matter where you are in your journey of faith, you&rsquo;re
            invited to discover your purpose and live it out at TGNM.
          </p>
          <div className="mt-8">
            <Button href="/about-us">Learn More About Us</Button>
          </div>
        </div>
      </section>

      {/* Featured: The Andrew Project */}
      {andrewProject && (
        <section className="bg-brand-50 py-20">
          <div className="mx-auto grid max-w-7xl gap-10 px-6 lg:grid-cols-2 lg:items-center">
            <div>
              <p className="font-display text-lg text-brand-600">
                The Andrew Month
              </p>
              <h2 className="mt-1 text-2xl font-extrabold tracking-tight text-ink-900 sm:text-3xl">
                Welcome to The Andrew Project
              </h2>
              <p className="mt-5 leading-relaxed text-ink-700">
                This coming month is our month of inviting family, friends,
                neighbours and strangers into the love of Christ. We have named
                this the Andrew Project Month!
              </p>
              <p className="mt-4 leading-relaxed text-ink-700">
                Andrew invited Simon Peter, his brother, to Christ. Why not
                invite everyone close to us &mdash; our family, our friends and
                our colleagues &mdash; just like Andrew, to meet Christ?
              </p>
              <div className="mt-8">
                <Button href={`/ministries/${andrewProject.slug}`}>
                  Join The Andrew Project
                </Button>
              </div>
            </div>
            <div className="rounded-2xl border border-brand-200 bg-white p-8">
              <h3 className="text-lg font-bold text-ink-900">
                Our primary role as Christians is to win souls for Jesus!
              </h3>
              <p className="mt-4 leading-relaxed text-ink-700">
                God is love, and this love which sent Jesus to the cross to save
                sinful man is within us. His spirit of self-denial and sacrifice
                possesses our lives, so that we are united with Him in this great
                crusade for the salvation of men and women.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Ministries */}
      <section className="py-20">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading eyebrow="Get Involved" title="Our Ministries" />
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {ministries.slice(0, 6).map((m) => (
              <MinistryCard key={m.slug} ministry={m} />
            ))}
          </div>
          <div className="mt-10 text-center">
            <Button href="/ministries">See All Ministries</Button>
          </div>
        </div>
      </section>

      {/* Verse */}
      <section className="bg-ink-900 py-20">
        <div className="mx-auto max-w-7xl px-6">
          <Scripture reference="Matthew 11:28-30">
            Come unto me, all ye that labour and are heavy laden, and I will
            give you rest. Take my yoke upon you, and learn of me; for I am meek
            and lowly in heart: and ye shall find rest unto your souls
          </Scripture>
        </div>
      </section>

      {/* Events */}
      <section className="py-20">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading eyebrow="What's On" title="Our Events" />
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {latestEvents.map((e) => (
              <EventCard key={e.slug} event={e} />
            ))}
          </div>
          <div className="mt-10 text-center">
            <Button href="/events">See All Events</Button>
          </div>
        </div>
      </section>

      {/* Latest sermon */}
      {latestSermon && (
        <section className="bg-slate-50 py-20">
          <div className="mx-auto max-w-3xl px-6">
            <SectionHeading eyebrow="Be Encouraged" title="Our Latest Sermon" />
            <div className="mt-12">
              <SermonCard sermon={latestSermon} />
            </div>
            <div className="mt-10 text-center">
              <Button href="/sermons">Browse the Sermon Archive</Button>
            </div>
          </div>
        </section>
      )}

      {/* Blog */}
      <section className="py-20">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeading eyebrow="Read" title="Latest From Our Blog" />
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {latestPosts.map((p) => (
              <PostCard key={p.slug} post={p} />
            ))}
          </div>
          <div className="mt-10 text-center">
            <Button href="/blog">Read the Blog</Button>
          </div>
        </div>
      </section>

      {/* Giving */}
      <section className="bg-accent-500 py-20">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <h2 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
            Send Your Gift Now!
          </h2>
          <p className="mt-4 leading-relaxed text-white/90">
            Your giving sends missionaries, feeds the hungry and carries the
            gospel to places we could never reach alone. Thank you for standing
            with us.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-4">
            <Button href={site.giving.url} variant="outline" external>
              Give Now
            </Button>
            <Button href={site.giving.causesUrl} variant="outline" external>
              See Our Causes
            </Button>
          </div>
        </div>
      </section>

      {/* Service times */}
      <section className="py-20">
        <div className="mx-auto max-w-5xl px-6">
          <SectionHeading eyebrow="Join Us" title="Our Order of Services" />
          <div className="mt-12 grid gap-8 sm:grid-cols-2">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-brand-700">
                Sunday
              </h3>
              <ul className="mt-4 divide-y divide-slate-200 border-t border-slate-200">
                {sundayServices.map((s) => (
                  <li key={s.name} className="py-4">
                    <p className="font-bold text-ink-900">{s.name}</p>
                    <p className="text-sm text-ink-700">
                      {s.time}
                      {s.note && (
                        <span className="text-brand-700"> · {s.note}</span>
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-brand-700">
                During the week
              </h3>
              <ul className="mt-4 divide-y divide-slate-200 border-t border-slate-200">
                {weeklyServices.map((s) => (
                  <li key={s.name} className="py-4">
                    <p className="font-bold text-ink-900">{s.name}</p>
                    <p className="text-sm text-ink-700">
                      {s.time}
                      {s.note && (
                        <span className="text-brand-700"> · {s.note}</span>
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <p className="mt-10 text-center text-ink-700">
            We invite you to explore our website, and we are confident you will
            be blessed a great deal.{" "}
            <Link
              href="/contact-us"
              className="font-bold text-brand-600 hover:text-brand-700"
            >
              Get in touch
            </Link>
            .
          </p>
        </div>
      </section>
    </>
  );
}
