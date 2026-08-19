/**
 * Global site settings: identity, contact details, socials and navigation.
 * Edit this file to change what appears in the header, footer and contact page.
 */

export const site = {
  name: "The Good News Mission",
  shortName: "TGNM",
  tagline: "Where Everyone is Someone!",
  description:
    "The Good News Mission is a dynamic, multicultural, missionary sending church in Nairobi, Kenya. Join us every Sunday to celebrate Jesus and our faith in Him.",
  url: "https://nuruplace.org",
  contact: {
    email: "pastor@thegoodnewsmission.org",
    phone: "+254 700706875",
    phoneHref: "tel:+254700706875",
    address: "Kangundo Road, Saika Estate, Near Kayole Junction",
    city: "Nairobi, Kenya",
  },
  giving: {
    url: "https://funding.thegoodnewsmission.org",
    causesUrl: "https://funding.thegoodnewsmission.org/causes",
  },
  socials: [
    { name: "Facebook", href: "https://facebook.com/thegoodnewsmissions/" },
    { name: "Twitter", href: "https://twitter.com/tgnfi" },
    { name: "Instagram", href: "https://instagram.com/thegoodnewsfellowship" },
    { name: "LinkedIn", href: "https://linkedin.com/in/good-news-462b91150/" },
  ],
} as const;

export type NavItem = {
  label: string;
  href: string;
  children?: { label: string; href: string }[];
};

export const mainNav: NavItem[] = [
  { label: "Home", href: "/" },
  {
    label: "About Us",
    href: "/about-us",
    children: [
      { label: "About The Good News Mission", href: "/about-us" },
      { label: "Our Faith", href: "/our-faith" },
      { label: "Our Statutes", href: "/our-statutes" },
      { label: "Our Strategic Plan", href: "/our-strategic-plan" },
      { label: "Message From Our Pastor", href: "/message-from-our-pastor" },
      { label: "Message From Our First Lady", href: "/message-from-our-first-lady" },
      { label: "Our Leadership", href: "/our-leadership" },
    ],
  },
  { label: "Ministries", href: "/ministries" },
  { label: "Sermons", href: "/sermons" },
  { label: "Events", href: "/events" },
  { label: "Blog", href: "/blog" },
  {
    label: "Media",
    href: "/gallery",
    children: [
      { label: "Announcements", href: "/announcements" },
      { label: "Gallery", href: "/gallery" },
      { label: "Videos", href: "/videos" },
    ],
  },
  { label: "Resources", href: "/resources" },
  { label: "Contact Us", href: "/contact-us" },
];

export const footerQuickLinks = [
  { label: "About Us", href: "/about-us" },
  { label: "Our Faith", href: "/our-faith" },
  { label: "Our Leadership", href: "/our-leadership" },
  { label: "Sermons", href: "/sermons" },
  { label: "Events", href: "/events" },
  { label: "Blog", href: "/blog" },
  { label: "Contact Us", href: "/contact-us" },
];
