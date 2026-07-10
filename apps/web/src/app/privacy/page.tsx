import { LegalPage, H } from "@/components/LegalPage";

export const metadata = { title: "Privacy Policy — Bethany House" };

export default function PrivacyPage() {
    return (
        <LegalPage title="Privacy Policy" updated="10 July 2026">
            <p>
                Bethany House ("we", "us") is a Kenyan maker of clergy apparel and
                communion supplies. This policy explains what personal information we
                collect when you contact us or order from us — including through our
                assistant, <strong>Neema</strong>, on WhatsApp, Facebook Messenger,
                Instagram and Facebook comments — and how we use and protect it.
            </p>

            <H>What we collect</H>
            <p>
                When you message us or order, we may collect: your name; your phone
                number or messaging handle; your city and country (for delivery); the
                messages, photos and voice notes you send us; garment measurements you
                share for made-to-order items; and your order and payment history
                (payments are processed by M-Pesa/our payment provider — we do not
                store card or mobile-money credentials).
            </p>

            <H>How we use it</H>
            <p>
                Solely to serve you: answering your questions, preparing quotes,
                making and delivering your order, following up on an enquiry, and
                keeping a record of your preferences (e.g. sizes) so we can serve you
                better next time. We do not sell or rent your information, and we do
                not use it for third-party advertising.
            </p>

            <H>Automated assistant</H>
            <p>
                Neema, our virtual sales assistant, may respond to your messages and
                comments. Your messages are processed by trusted AI service providers
                acting on our instructions to generate those responses. Our staff
                supervise these conversations and can take over at any time.
            </p>

            <H>Where your data lives</H>
            <p>
                Conversations reach us through the platforms you use (Meta's WhatsApp,
                Messenger, Instagram — governed also by Meta's own terms) and are
                stored on our secured systems. We keep information only as long as
                needed for service, our records, and legal obligations.
            </p>

            <H>Your rights</H>
            <p>
                You may ask us at any time to see, correct, or delete the personal
                information we hold about you — see our{" "}
                <a href="/data-deletion" style={{ color: "#589b31" }}>Data Deletion page</a>{" "}
                for exactly how. We comply with the Kenya Data Protection Act, 2019.
            </p>

            <H>Contact</H>
            <p>
                Message us on WhatsApp at +254 727 891 989 or through our Facebook
                page (Bethany House) with any privacy question or request.
            </p>
        </LegalPage>
    );
}
