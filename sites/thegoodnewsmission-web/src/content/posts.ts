/** Blog articles. `body` is an array of paragraphs. */

export type Post = {
  slug: string;
  title: string;
  author: string;
  date: string; // ISO date
  excerpt: string;
  body: string[];
};

export const posts: Post[] = [
  {
    slug: "messed-up-yet-qualified-by-grace",
    title: "Messed Up, Yet Qualified by Grace",
    author: "The Good News Mission",
    date: "2022-09-18",
    excerpt:
      "Messed up and broken, and yet God qualified me by His grace. Oh the grace! Grace has continued to qualify…",
    body: [
      "Messed up and broken, and yet God qualified me by His grace. Oh the grace!",
      "Grace has continued to qualify those that the world had long disqualified. It is not the strong, the polished or the impressive that God calls — it is those who know they have nothing to offer but a willing heart.",
      "If you have been waiting until you are good enough to come to God, you will wait forever. Come as you are. Grace will do the qualifying.",
    ],
  },
  {
    slug: "love-so-great-love-so-deep-love-so-pure",
    title: "Love So Great, Love So Deep, Love So Pure!",
    author: "The Good News Mission",
    date: "2022-06-12",
    excerpt:
      "For here is the way God loved the world — He gave His only, unique Son as a gift.",
    body: [
      "For here is the way God loved the world: He gave His only, unique Son as a gift. So now everyone who believes in Him will never perish, but experience everlasting life.",
      "This is a love that did not wait for us to deserve it, and does not withdraw when we fail. It is great enough to cover every sin, deep enough to reach every person, and pure enough to change whoever receives it.",
    ],
  },
  {
    slug: "start-your-new-life-with-christ",
    title: "Start Your New Life With Christ",
    author: "The Good News Mission",
    date: "2022-04-10",
    excerpt:
      "Become new now! What it means to surrender your life to Jesus, and the first steps that follow.",
    body: [
      "The only means of being cleansed from sin is through repentance and faith in the precious blood of Christ. Regeneration by the Holy Spirit is absolutely essential for personal salvation.",
      "If you are ready to begin, pray simply and honestly: admit your need, believe that Jesus died and rose for you, and ask Him to take charge of your life.",
      "Then tell somebody. Find a church family. Get into the word. A new life is meant to be lived out among people who will walk with you.",
    ],
  },
  {
    slug: "how-do-you-respond-to-the-word-of-god",
    title: "How Do You Respond to the Word of God?",
    author: "The Good News Mission",
    date: "2022-02-20",
    excerpt:
      "The same seed falls on four kinds of ground. The difference is never the seed — it is the soil.",
    body: [
      "In the parable of the sower, the same seed falls on four kinds of ground. The difference in the harvest is never the seed. It is the soil.",
      "Some hear and never understand. Some receive with joy but have no root. Some let the cares of this life choke the word. And some hear, understand and bear fruit — thirty, sixty, a hundredfold.",
      "The question is not whether the word is being preached. The question is what kind of ground you are.",
    ],
  },
];

export function getPost(slug: string): Post | undefined {
  return posts.find((p) => p.slug === slug);
}
