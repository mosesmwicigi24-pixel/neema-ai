/** Sermon archive. `audioUrl` / `videoUrl` are optional. */

export type Sermon = {
  slug: string;
  title: string;
  speaker: string;
  date: string; // ISO date
  scripture?: string;
  summary: string;
  audioUrl?: string;
  videoUrl?: string;
};

export const sermons: Sermon[] = [
  {
    slug: "messed-up-yet-qualified-by-grace",
    title: "Messed Up, Yet Qualified by Grace",
    speaker: "Pastor, The Good News Mission",
    date: "2022-09-18",
    scripture: "Ephesians 2:8–9",
    summary:
      "Messed up and broken, and yet God qualified me by His grace. Grace has continued to qualify those the world has written off.",
  },
  {
    slug: "love-so-great-love-so-deep",
    title: "Love So Great, Love So Deep, Love So Pure!",
    speaker: "Pastor, The Good News Mission",
    date: "2022-06-12",
    scripture: "John 3:16",
    summary:
      "For here is the way God loved the world — He gave His only, unique Son as a gift.",
  },
  {
    slug: "start-your-new-life-with-christ",
    title: "Start Your New Life With Christ",
    speaker: "Pastor, The Good News Mission",
    date: "2022-04-10",
    scripture: "2 Corinthians 5:17",
    summary:
      "What it means to become new, and the first steps of a life surrendered to Jesus.",
  },
  {
    slug: "how-do-you-respond-to-the-word-of-god",
    title: "How Do You Respond to the Word of God?",
    speaker: "Pastor, The Good News Mission",
    date: "2022-02-20",
    scripture: "Matthew 13:1–23",
    summary:
      "The parable of the sower, and the four kinds of ground the word of God falls on.",
  },
];
