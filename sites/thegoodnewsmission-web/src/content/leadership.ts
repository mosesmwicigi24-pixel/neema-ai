/**
 * Church leadership. Add a `photo` path (e.g. "/leadership/name.jpg") once
 * photographs have been added to /public.
 */

export type Leader = {
  name: string;
  role: string;
  bio?: string;
  photo?: string;
};

export const leadership: Leader[] = [
  {
    name: "Name to be confirmed",
    role: "Senior Pastor",
    bio: "Leads The Good News Mission and its missionary sending work.",
  },
  {
    name: "Name to be confirmed",
    role: "First Lady",
    bio: "Serves alongside the Senior Pastor with particular care for the women of the fellowship.",
  },
  {
    name: "Name to be confirmed",
    role: "Department Leader — United Guardians of Faith (UGF)",
  },
  {
    name: "Name to be confirmed",
    role: "Department Leader — Ablaze Worship",
  },
  {
    name: "Name to be confirmed",
    role: "Department Leader — Media",
  },
  {
    name: "Name to be confirmed",
    role: "Department Leader — Children Ministry",
  },
];
