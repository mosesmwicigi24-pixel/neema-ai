/**
 * Ministries / departments. Each entry becomes a card on /ministries and a
 * detail page at /ministries/[slug].
 */

export type Ministry = {
  slug: string;
  name: string;
  summary: string;
  body: string[];
  leader?: string;
};

export const ministries: Ministry[] = [
  {
    slug: "ablaze-worship",
    name: "Ablaze Worship",
    summary:
      "Our worship ministry — leading the congregation into the presence of God and raising up worship leaders.",
    body: [
      "Are you a worship leader in your church? Do you love music and long to see the presence of God fill a room? Ablaze Worship exists to raise, train and release worshippers who lead from a place of intimacy with God rather than performance.",
      "The ministry runs the Ablaze Worship Experience, an extended evening of open worship held on the second Sunday of the month, along with weekly rehearsals and mentorship for singers and instrumentalists.",
    ],
  },
  {
    slug: "media-department",
    name: "Media Department",
    summary:
      "Sound, live streaming, photography and video — carrying the message beyond the four walls of the building.",
    body: [
      "How should the church use technology to be more effective? There are churches that have embraced technology and, in doing so, have multiplied their reach many times over.",
      "The Media Department handles sound, live streaming, photography, video production and the church's online presence, so that every service can reach people who are not in the room.",
    ],
  },
  {
    slug: "children-ministry",
    name: "Children Ministry",
    summary:
      "Teaching children and teenagers the word of God in a way they can understand, remember and live out.",
    body: [
      "What we aim to achieve with the Children's Ministry is to establish TAS — Teens, Adventurers and the Sunday School — so that every age group is taught the word of God at the level they can receive it.",
      "We nurture children in scripture, prayer and service, and give them room to discover and use their gifts from an early age.",
    ],
  },
  {
    slug: "the-andrew-project",
    name: "The Andrew Project",
    summary:
      "A soul-winning project for every believer, modelled on Andrew, who brought his brother Simon Peter to Christ.",
    body: [
      "The Andrew Project is a project for all Christians. The title of this project comes from the example of Andrew, who invited Simon Peter, his brother, to Christ.",
      "Why not invite everyone close to us — our family, our friends and our colleagues — just like Andrew did, to meet Christ?",
      "Each year we set aside the Andrew Month: a month of inviting family, friends, neighbours and strangers into the love of Christ.",
    ],
  },
  {
    slug: "united-guardians-of-faith",
    name: "United Guardians of Faith (UGF)",
    summary:
      "A department committed to guarding and growing the faith of the fellowship through prayer and discipleship.",
    body: [
      "United Guardians of Faith (UGF) is a department of The Good News Mission committed to standing in the gap for the church in prayer, and to guarding sound doctrine within the fellowship.",
      "The department disciples believers into maturity, so that they are able to give an answer for the hope that is in them.",
    ],
  },
  {
    slug: "tabitha-ministry",
    name: "Tabitha Ministry",
    summary:
      "Practical compassion for widows, orphans and the vulnerable in our community.",
    body: [
      "Tabitha Ministry is a department of The Good News Mission that aims to help the widowed, the orphaned and the vulnerable in the communities around us.",
      "Named after Tabitha of Joppa, who was 'full of good works and acts of charity', the ministry provides food, clothing, counselling and practical support to those in need.",
    ],
  },
  {
    slug: "cyber-missions",
    name: "Cyber Missions",
    summary:
      "Online outreach — using the internet and social media to reach nations that are otherwise closed to the gospel.",
    body: [
      "At The Good News Mission we have a department for Cyber Missions and Online Outreach Ministry. We harness the power of social media and use it to reach more people, including in countries that are suppressing Christianity.",
      "We use our website to disseminate information to people across the world on soul winning and biblical teaching, giving particular emphasis to nations where a physical missionary presence is difficult.",
    ],
  },
];

export function getMinistry(slug: string): Ministry | undefined {
  return ministries.find((m) => m.slug === slug);
}
