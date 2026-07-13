import { LegalPage, H } from "@/components/LegalPage";

export const metadata = { title: "Data Deletion — Bethany House" };

export default function DataDeletionPage() {
    return (
        <LegalPage title="Data Deletion Instructions" updated="10 July 2026">
            <p>
                You can ask us to delete the personal information Bethany House holds
                about you — your contact details, conversation history with us
                (including our assistant Neema), and profile information — at any time.
            </p>

            <H>How to request deletion</H>
            <p>
                Send us a message saying <em>"Please delete my data"</em> through any
                of these channels:
            </p>
            <ul className="list-disc pl-6 space-y-1">
                <li>WhatsApp: <strong>+254 785 490 805</strong></li>
                <li>Facebook Messenger: message our page, <strong>Bethany House</strong></li>
                <li>Instagram: DM <strong>@bethanyhouse</strong></li>
            </ul>
            <p>
                We will confirm your identity (to protect your data from someone else
                requesting its deletion), then delete your personal information from
                our systems within <strong>30 days</strong> and confirm to you when it
                is done.
            </p>

            <H>What we may retain</H>
            <p>
                Records we are legally required to keep (e.g. tax records of completed
                purchases) are retained for the statutory period, and only those.
            </p>

            <H>Facebook / Instagram data</H>
            <p>
                Deleting your data with us does not delete your copy of the
                conversation inside WhatsApp, Messenger or Instagram — those live in
                your own account, governed by Meta's tools and policies.
            </p>
        </LegalPage>
    );
}
