/**
 * Long-form static pages. Each page is a title, an optional intro and a list
 * of sections. Sections render as a heading followed by paragraphs and an
 * optional bullet list.
 */

export type PageSection = {
  heading?: string;
  paragraphs?: string[];
  bullets?: string[];
};

export type StaticPage = {
  title: string;
  intro?: string;
  sections: PageSection[];
};

export const aboutPage: StaticPage = {
  title: "About The Good News Mission",
  intro:
    "The Good News Mission is a dynamic, multicultural community and a missionary sending church. The church offers relevant teaching and amazing worship as part of every Sunday worship gathering. Get ready to experience church in a whole new way — join us every Sunday, 10:00 AM to 1:00 PM, to celebrate Jesus and our faith in Him.",
  sections: [
    {
      heading: "Who We Are",
      paragraphs: [
        "The church is a fellowship where those who know Christ are bound together in the Spirit; a lecture room where great truths are expounded and teaching on every Christian virtue is given; and a nursery where young Christians are grown into maturity.",
        "The Good News Mission is more than a church. It is a family of believers who have come together to share the love of God. Our immediate task is to help you become the person God made you to be. No matter where you are in your journey of faith, you are invited to discover your purpose and live it out at TGNM.",
      ],
    },
    {
      heading: "Our Mission",
      paragraphs: [
        "Our mission is to preach the Good News of our Lord Jesus Christ that brings salvation to every soul that hears and believes, across the world. We are determined to bring souls to Christ, then teach them, train them in the area of their gifting, and later commission them to win more souls for Jesus.",
      ],
    },
    {
      heading: "Our Vision",
      paragraphs: [
        "Our vision is to go out into the ripened world and win more souls for Jesus. We intend to leverage every available tool — technology, people, corporations and airwaves — to reach people across the world, with particular emphasis on nations where the gospel is least accessible.",
      ],
    },
    {
      heading: "How We Reach Out",
      paragraphs: ["We intend to use every available tool to reach out. They include:"],
      bullets: [
        "Harnessing the power of social media and using it to reach more people, including in countries that are suppressing Christianity.",
        "Using our website to disseminate information to people across the world on soul winning and biblical teaching.",
        "Empowering brethren by training them to be effective missionaries in their own societies.",
        "Commissioning missionaries both locally and internationally, and much more as God enables us.",
      ],
    },
    {
      heading: "The Great Commission",
      paragraphs: [
        "“Therefore go and make disciples of all nations, baptizing them in the name of the Father and of the Son and of the Holy Spirit, and teaching them to obey everything I have commanded you. And surely I am with you always, to the very end of the age.” — Matthew 28:19–20",
      ],
    },
  ],
};

export const faithPage: StaticPage = {
  title: "Our Faith",
  intro:
    "What we believe, and why it shapes everything we do as a missionary sending church.",
  sections: [
    {
      heading: "What We Believe",
      bullets: [
        "The Bible is the inspired, infallible and authoritative written word of God.",
        "There is one God, eternally existing in three persons: God the Father, God the Son and God the Holy Ghost.",
        "In the deity of our Lord Jesus Christ: His virgin birth, His sinless life, His miracles, His vicarious and atoning death, His bodily resurrection, His ascension to the right hand of the Father, and His future return to earth in power and glory.",
        "In the blessed hope and the rapture of the Church at Christ's coming.",
        "The only means of being cleansed from sin is through repentance and faith in the precious blood of Christ.",
        "Regeneration by the Holy Spirit is absolutely essential for personal salvation.",
        "In water baptism by immersion.",
        "The redemptive work of Christ on the cross provides healing of the human body in answer to believing prayer.",
        "The baptism in the Holy Spirit, according to Acts 2:4, is given to believers who ask for it.",
        "In the sanctifying power of the Holy Spirit, by whose indwelling the Christian is enabled to live a holy life.",
        "In the Lord's Supper.",
        "In the millennial or second coming of Jesus: first, to resurrect the righteous dead and receive the living saints to Him in the air; second, to reign on earth a thousand years.",
        "In the bodily resurrection; eternal life for the righteous and eternal punishment for the wicked.",
      ],
    },
    {
      heading: "Every Believer Is Primarily a Missionary",
      paragraphs: [
        "Soul winning is not just an ambition for a few choice souls who wish to be accounted wise in the sight of God. It is a statement which sets out the great task in which every believer is involved because of his or her relationship with God.",
        "“The fruit of the righteous is a tree of life, and he that wins souls is wise.” — Proverbs 11:30",
      ],
    },
    {
      heading: "The Apostles' Creed",
      paragraphs: [
        "I believe in God, the Father almighty, creator of heaven and earth.",
        "I believe in Jesus Christ, God's only Son, our Lord, who was conceived by the Holy Spirit, born of the Virgin Mary, suffered under Pontius Pilate, was crucified, died, and was buried; He descended to the dead. On the third day He rose again; He ascended into heaven, He is seated at the right hand of the Father, and He will come to judge the living and the dead.",
        "I believe in the Holy Spirit, the holy catholic Church, the communion of saints, the forgiveness of sins, the resurrection of the body, and the life everlasting. Amen.",
      ],
    },
  ],
};

export const statutesPage: StaticPage = {
  title: "Our Statutes",
  intro:
    "The statutes that govern the order, membership and administration of The Good News Mission.",
  sections: [
    {
      heading: "Content to be added",
      paragraphs: [
        "The full text of the church statutes will be published here. Replace this section in src/content/pages.ts with the official document once it has been supplied.",
      ],
    },
  ],
};

export const strategicPlanPage: StaticPage = {
  title: "Our Strategic Plan",
  intro:
    "The desire of The Good News Mission is to reach out to as many people as possible with the Good News of Jesus Christ that saves. We are therefore putting in place processes that will help us realise this great commission of our Lord Jesus Christ.",
  sections: [
    {
      heading: "Aligning Our Programmes to Outreach",
      paragraphs: [
        "We are aligning our church programmes to emphasise outreach and soul winning. This includes committing 80% of our church finances towards outreach and soul winning.",
      ],
    },
    {
      heading: "Training and Commissioning Missionaries",
      paragraphs: [
        "We are teaching church members on outreach and soul winning by holding seminars and trainings. The long-term outcome desired from this process is to have moulded a team of active missionaries who will be deployed within and outside the country to do the mission work.",
      ],
    },
    {
      heading: "Reaching the Least Reached",
      paragraphs: [
        "We give particular emphasis to nations where the gospel is least accessible, using technology, partnerships and airwaves to reach people that a physical missionary presence cannot easily reach.",
      ],
    },
  ],
};

export const pastorMessagePage: StaticPage = {
  title: "Message From Our Pastor",
  intro:
    "I take this wonderful moment to welcome you to our church.",
  sections: [
    {
      paragraphs: [
        "Our church is driven by the desire to reach every soul with the good news of our Lord Jesus Christ — the good news that brings salvation to the lost. We are a group of people committed to following Jesus. This means that we encourage prayer in church and throughout life, and that we show love to people outside the church through generosity, invitation and compassion.",
        "We truly love all people that fellowship here, as well as all visitors that come our way. We also take great interest in the development of individual members. We nurture their talents and gifts and then give them room to serve God in their area of gifting.",
        "Not only do we regard those that are of the fellowship of the brethren, but we also reach out to all people that are not born again with love and with joy. We give a hand of friendship to them too by praying with them, giving food to the hungry, offering guidance and counselling to those that need it, and much more.",
        "We cannot explicitly state all things here — but if you can come, you will experience a wonderful place to serve God.",
        "God bless you as you plan to come and fellowship with us.",
      ],
    },
    {
      heading: "On Evangelism",
      paragraphs: [
        "“Evangelism is grounded in the very nature of God. Not only is Jesus the motivating power within us, but He is also the great example to us. Paul states: Let this mind be in you which was also in Christ Jesus, who being in the form of God, did not consider it robbery to be equal with God, but made Himself of no reputation… but humbled Himself… became obedient to the point of death, even the death of the cross.”",
        "Evangelism is neither debatable nor optional; it is obligatory. The gospel must be proclaimed. All who know Him must make Him known.",
      ],
    },
  ],
};

export const firstLadyMessagePage: StaticPage = {
  title: "Message From Our First Lady",
  intro: "A warm welcome to every woman, every family and every visitor.",
  sections: [
    {
      heading: "Content to be added",
      paragraphs: [
        "The First Lady's message will be published here. Replace this section in src/content/pages.ts with the final text once it has been supplied.",
      ],
    },
  ],
};

export const resourcesPage: StaticPage = {
  title: "Resources",
  intro:
    "Teaching materials, study guides and downloads to help you grow in the word.",
  sections: [
    {
      heading: "Coming soon",
      paragraphs: [
        "Resources will be listed here as they are published. Add them in src/content/pages.ts, or replace this page with a downloads listing once files are available.",
      ],
    },
  ],
};
