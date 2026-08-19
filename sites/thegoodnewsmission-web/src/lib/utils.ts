import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Formats an ISO date as e.g. "23 October 2022". */
export function formatDate(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Sorts a list of dated records newest first (does not mutate the input). */
export function byDateDesc<T extends { date: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => b.date.localeCompare(a.date));
}
