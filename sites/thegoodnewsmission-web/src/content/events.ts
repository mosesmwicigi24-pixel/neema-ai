/** Upcoming and past events. Sorted newest first when rendered. */

export type ChurchEvent = {
  slug: string;
  title: string;
  date: string; // ISO date — used for sorting and <time>
  timeLabel: string;
  location: string;
  summary: string;
};

export const events: ChurchEvent[] = [
  {
    slug: "ablaze-worship-experience-october",
    title: "Ablaze Worship Experience — October Edition",
    date: "2022-10-23",
    timeLabel: "2:00 PM – 7:30 PM",
    location: "The Good News Mission Church, Saika",
    summary:
      "An extended evening of open worship with the Ablaze team. Come expectant — no programme, just the presence of God.",
  },
  {
    slug: "partners-dinner",
    title: "Partners Dinner Event",
    date: "2021-07-17",
    timeLabel: "5:30 PM – 8:00 PM",
    location: "The Good News Mission Church",
    summary:
      "An evening with the partners who make the mission work possible, sharing the year's testimonies and the road ahead.",
  },
  {
    slug: "ablaze-open-worship-experience",
    title: "Ablaze Open Worship Experience",
    date: "2019-06-15",
    timeLabel: "4:00 PM – 6:00 PM",
    location: "The Good News Mission, Saika",
    summary:
      "Open worship for the whole family — singers, instrumentalists and anyone who simply wants to worship.",
  },
  {
    slug: "fundraising-dinner",
    title: "Fundraising Dinner",
    date: "2019-03-02",
    timeLabel: "6:00 PM",
    location: "The Good News Mission Church",
    summary:
      "A fundraising evening towards the church building and outreach programmes.",
  },
  {
    slug: "church-commissioning",
    title: "Church Commissioning",
    date: "2018-12-09",
    timeLabel: "10:00 AM",
    location: "The Good News Mission, Saika",
    summary:
      "The commissioning of The Good News Mission church building at Saika.",
  },
];
