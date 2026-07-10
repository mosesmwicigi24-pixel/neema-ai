import { LegalPage, H } from "@/components/LegalPage";

export const metadata = { title: "Terms of Service — Bethany House" };

export default function TermsPage() {
    return (
        <LegalPage title="Terms of Service" updated="10 July 2026">
            <p>
                These terms apply when you browse our catalogue, message us (including
                our assistant Neema on WhatsApp, Messenger, Instagram or Facebook), or
                place an order with Bethany House, Nairobi, Kenya.
            </p>

            <H>Orders & made-to-order items</H>
            <p>
                Most clergy apparel and vestments are made to order. For sized items
                we confirm your measurements before production begins. An order is
                confirmed when we issue an order number; production timelines are
                communicated per order and are estimates, not guarantees.
            </p>

            <H>Prices & payment</H>
            <p>
                Prices are quoted in Kenyan Shillings (KES) for Kenyan customers and
                in US Dollars (USD) for international customers. Payment is made
                through the secure payment link we send with your order confirmation;
                checkout settles in KES. We never ask you to pay to a personal number.
            </p>

            <H>Delivery</H>
            <p>
                We ship from Nairobi, Kenya, worldwide. Delivery costs and timelines
                depend on your location and are agreed before you pay.
            </p>

            <H>Returns & issues</H>
            <p>
                Made-to-order garments are crafted to your measurements; if something
                isn't right, contact us and we will work with you to make it right.
                Ready-made items may be returned unused within a reasonable period.
            </p>

            <H>The assistant</H>
            <p>
                Neema is an automated assistant supervised by our staff. It provides
                information from our live catalogue in good faith; obvious errors in
                price or availability do not form a binding offer. You can ask for a
                human at any time.
            </p>

            <H>Contact & law</H>
            <p>
                Questions: WhatsApp +254 727 891 989 or our Facebook page. These terms
                are governed by the laws of Kenya.
            </p>
        </LegalPage>
    );
}
