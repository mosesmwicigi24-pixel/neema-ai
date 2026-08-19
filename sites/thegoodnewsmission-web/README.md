# The Good News Mission — Website

Website for [The Good News Mission](https://nuruplace.org), a missionary sending
church on Kangundo Road, Saika Estate, Nairobi.

Built with **Next.js 16** (App Router), **React 19**, **TypeScript** and
**Tailwind CSS v4**.

---

## Getting started

```bash
npm install
npm run dev      # http://localhost:3000
```

Other scripts:

| Command | What it does |
|---|---|
| `npm run dev` | Development server with hot reload |
| `npm run build` | Production build |
| `npm start` | Serve the production build |
| `npm run lint` | ESLint |

---

## Editing the site

**Almost all text lives in `src/content/`.** You do not need to touch React
components to change wording, add a sermon, or publish a blog post.

| File | Controls |
|---|---|
| `site.ts` | Church name, tagline, phone, email, address, giving links, social links, and the navigation menu |
| `services.ts` | Sunday and midweek service times |
| `ministries.ts` | The seven ministries — each becomes a card and a `/ministries/<slug>` page |
| `events.ts` | Events, split automatically into upcoming and past by date |
| `sermons.ts` | Sermon archive |
| `posts.ts` | Blog articles — each becomes a `/blog/<slug>` page |
| `leadership.ts` | Names, roles and bios on `/our-leadership` |
| `pages.ts` | Long-form pages: About, Our Faith, Statutes, Strategic Plan, the Pastor's and First Lady's messages, Resources |

### Adding a blog post

Add an entry to the `posts` array in `src/content/posts.ts`:

```ts
{
  slug: "a-url-friendly-name",
  title: "Your Title",
  author: "The Good News Mission",
  date: "2026-08-19",          // ISO — used for sorting
  excerpt: "One or two sentences shown on the blog listing.",
  body: ["First paragraph.", "Second paragraph."],
}
```

The listing page, the article page, and the sitemap all pick it up automatically.

Events, sermons and ministries work the same way.

---

## Project structure

```
src/
├─ app/                    App Router pages — one folder per route
│  ├─ layout.tsx           Root layout: fonts, header, footer, metadata
│  ├─ page.tsx             Home page
│  ├─ globals.css          Tailwind import + brand palette
│  ├─ sitemap.ts           Generated from the content files
│  └─ robots.ts
├─ components/
│  ├─ site-header.tsx      Top bar, logo, desktop nav
│  ├─ mobile-nav.tsx       Mobile menu (the only client component)
│  ├─ site-footer.tsx
│  ├─ ui.tsx               PageHero, SectionHeading, Scripture, Button, …
│  └─ cards.tsx            Ministry / event / sermon / post cards
├─ content/                ← edit the site here
└─ lib/utils.ts            cn(), formatDate(), byDateDesc()
```

### Brand colours

Taken from the current nuruplace.org stylesheet and defined as Tailwind theme
tokens in `src/app/globals.css`:

| Token | Hex | Use |
|---|---|---|
| `brand-600` | `#060eff` | Primary blue — buttons, links |
| `brand-700` | `#2428a6` | Deep blue — scripture band |
| `accent-500` | `#dc2b0f` | Accent red — Give button, giving section |
| `ink-900` | `#0b1020` | Near-black — hero and footer |

Fonts are **Montserrat** (body and headings) and **Merienda** (scripture and
display accents), loaded through `next/font`.

---

## Status

This is a rebuild of nuruplace.org. The current live site runs on a PHP
CodeIgniter CMS whose source is not available, so the structure, wording and
brand colours were reproduced from the live pages.

**Complete:** Home, About, Our Faith, Our Strategic Plan, Message From Our
Pastor, Our Leadership, Ministries (listing + 7 detail pages), Sermons, Events,
Blog (listing + articles), Contact, plus sitemap and robots.

**Still needs real content:**

- `our-statutes` and `message-from-our-first-lady` — placeholder text in `pages.ts`
- `our-leadership` — real names, roles and photographs
- `announcements`, `gallery`, `videos`, `shop` — placeholder pages
- Photography throughout. No images are bundled: the hero and cards use colour
  and type rather than hotlinking assets from the live site. Drop photographs
  into `public/` and reference them from the content files.
- The contact page describes where a form would go but does not ship one — a
  form needs a destination (an email service or a route handler) so submissions
  are not silently lost.

---

## Deploying

The project is a standard Next.js app and deploys to Vercel with no
configuration. For a self-hosted VPS, add `output: "standalone"` to
`next.config.ts` and build a container the same way `apps/web` does in the
neema-ai repository.
