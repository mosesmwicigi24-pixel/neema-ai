/** Weekly service schedule shown on the home page and contact page. */

export type ServiceSlot = {
  name: string;
  time: string;
  note?: string;
};

export const sundayServices: ServiceSlot[] = [
  { name: "Discipleship Service", time: "8:00 – 9:30 AM" },
  { name: "Main Service", time: "10:30 AM – 1:00 PM" },
  {
    name: "Worship Experience",
    time: "3:00 – 6:00 PM",
    note: "Second Sunday of the month",
  },
];

export const weeklyServices: ServiceSlot[] = [
  {
    name: "Worship Experience Rehearsal",
    time: "10:00 PM – 5:00 AM",
    note: "Wednesday night",
  },
  { name: "Prayer Day", time: "Every Friday" },
];
