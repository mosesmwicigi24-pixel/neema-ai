import type { Metadata } from "next";
import { Mail, MapPin, Phone } from "lucide-react";
import { PageHero } from "@/components/ui";
import { site } from "@/content/site";
import { sundayServices, weeklyServices } from "@/content/services";

export const metadata: Metadata = { title: "Contact Us" };

export default function ContactPage() {
  return (
    <>
      <PageHero
        title="Contact Us"
        subtitle="We would love to hear from you. Come and visit, call, or send us a message."
      />
      <div className="mx-auto grid max-w-7xl gap-12 px-6 py-16 lg:grid-cols-2">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight text-ink-900">
            Find us
          </h2>
          <p className="mt-4 leading-relaxed text-ink-700">
            The Good News Mission is a missionary sending church. We desire to
            show the love of Christ to all people through sharing the Good News
            of our Lord Jesus Christ with every soul across the world. Our
            calling is one that says &ldquo;Go ye out&rdquo;, rather than asking
            people to come and forever remain within the four walls of a
            building.
          </p>

          <ul className="mt-8 space-y-5">
            <li className="flex gap-4">
              <MapPin className="mt-1 size-5 shrink-0 text-brand-600" aria-hidden />
              <div>
                <p className="font-bold text-ink-900">Address</p>
                <p className="text-ink-700">{site.contact.address}</p>
                <p className="text-ink-700">{site.contact.city}</p>
              </div>
            </li>
            <li className="flex gap-4">
              <Phone className="mt-1 size-5 shrink-0 text-brand-600" aria-hidden />
              <div>
                <p className="font-bold text-ink-900">Phone</p>
                <a
                  href={site.contact.phoneHref}
                  className="text-brand-600 hover:text-brand-700"
                >
                  {site.contact.phone}
                </a>
              </div>
            </li>
            <li className="flex gap-4">
              <Mail className="mt-1 size-5 shrink-0 text-brand-600" aria-hidden />
              <div>
                <p className="font-bold text-ink-900">Email</p>
                <a
                  href={`mailto:${site.contact.email}`}
                  className="break-all text-brand-600 hover:text-brand-700"
                >
                  {site.contact.email}
                </a>
              </div>
            </li>
          </ul>
        </div>

        <div>
          <h2 className="text-xl font-extrabold tracking-tight text-ink-900">
            Service times
          </h2>
          <ul className="mt-4 divide-y divide-slate-200 border-y border-slate-200">
            {[...sundayServices, ...weeklyServices].map((s) => (
              <li key={s.name} className="flex justify-between gap-4 py-4">
                <span className="font-bold text-ink-900">{s.name}</span>
                <span className="text-right text-sm text-ink-700">
                  {s.time}
                  {s.note && (
                    <span className="block text-brand-700">{s.note}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>

          <div className="mt-8 rounded-lg border border-dashed border-slate-300 p-6 text-sm leading-relaxed text-ink-700">
            <p className="font-bold text-ink-900">A contact form goes here</p>
            <p className="mt-2">
              A form needs somewhere to send messages. Wire it to an email
              service (Resend, Formspree) or a route handler at{" "}
              <code className="rounded bg-slate-100 px-1.5 py-0.5">
                src/app/api/contact/route.ts
              </code>{" "}
              before adding one, so submissions are not silently lost.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
