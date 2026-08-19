import type { MetadataRoute } from "next";
import { site } from "@/content/site";
import { ministries } from "@/content/ministries";
import { posts } from "@/content/posts";

const staticRoutes = [
  "",
  "/about-us",
  "/our-faith",
  "/our-statutes",
  "/our-strategic-plan",
  "/message-from-our-pastor",
  "/message-from-our-first-lady",
  "/our-leadership",
  "/ministries",
  "/sermons",
  "/events",
  "/blog",
  "/announcements",
  "/gallery",
  "/videos",
  "/resources",
  "/shop",
  "/contact-us",
];

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    ...staticRoutes.map((path) => ({ url: `${site.url}${path}` })),
    ...ministries.map((m) => ({ url: `${site.url}/ministries/${m.slug}` })),
    ...posts.map((p) => ({ url: `${site.url}/blog/${p.slug}` })),
  ];
}
