import SwiftUI
import UIKit
import NeemaCore

/// The order detail (Android `OrderDetail`): the web Modal's title bar, the
/// customer, a meta grid, the hub linkage, the items with their total, the
/// note Neema sent, a shortcut to the thread and the status moves.
struct OrderDetailView: View {
    let order: Order
    let busy: Bool
    let onStatus: (String) -> Void
    let onClose: () -> Void
    /// The side sheet draws its own title bar.
    var titleBar: Bool = true
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL

    private var meta: StatusMeta { OrderUi.statusMeta(order.status) }
    private var actions: [String] { OrderUi.actions(from: order.status) }
    private var name: String { order.customerName.isEmpty ? "Unknown" : order.customerName }
    private var hubHref: String? { OrderUi.hubOrderHref(order) }
    private var hub: StatusMeta? { OrderUi.hubMeta(order) }
    private var publicUrl: String? { order.hubPublicUrl.flatMap { $0.isEmpty ? nil : $0 } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if titleBar { ModalTitleBar(title: "Order — \(name)", onClose: onClose).padding(.top, 16) }
                VStack(alignment: .leading, spacing: 0) {
                    customer
                    metaGrid.padding(.top, 16)
                    SectionLabel(text: "Hub").padding(.top, 16)
                    hubSection
                    SectionLabel(text: "Items").padding(.top, 16)
                    items
                    if let note = order.replyText, !note.isEmpty { noteBox(note).padding(.top, 16) }
                    // Customer thread shortcut
                    WebBtn(label: "Open conversation", variant: .outline, size: .md) { app.openConversationFor(order.waId) }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 16)
                    // Status moves — shown to every agent, as OrdersView does (it has no manage_orders check).
                    if !actions.isEmpty {
                        FlowLayout(spacing: 8, lineSpacing: 8) {
                            ForEach(actions, id: \.self) { next in
                                WebBtn(label: "Mark as \(OrderUi.statusMeta(next).label)", variant: next == "cancelled" ? .danger : .primary,
                                       enabled: !busy, busy: busy, size: .md) { onStatus(next) }
                            }
                        }
                        .padding(.top, 10)
                    }
                }
                .padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 24)
            }
        }
    }

    // ── Sections ──────────────────────────────────────────────────────────────

    private func box<Content: View>(radius: CGFloat = 12, @ViewBuilder _ content: () -> Content) -> some View {
        content()
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: radius, style: .continuous).fill(c.bg))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(c.bg3))
    }

    private var customer: some View {
        box {
            HStack(spacing: 12) {
                AvatarView(name: name, size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    // The badge sits at the right while the name fits beside it, else under it —
                    // a phone number never splits across lines to make room.
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 8) {
                            nameText
                            Spacer(minLength: 0)
                            StatusBadge(text: meta.label, tone: meta.tone, fontSize: 12, radius: 8, hPad: 8, vPad: 4)
                        }
                        VStack(alignment: .leading, spacing: 4) {
                            nameText
                            StatusBadge(text: meta.label, tone: meta.tone, fontSize: 12, radius: 8, hPad: 8, vPad: 4)
                        }
                    }
                    if let p = OrderUi.phoneLine(order, displayedName: name) {
                        Text(p.unbroken).font(NeemaFont.mono(12)).foregroundColor(c.textDim)
                    }
                }
            }
        }
    }

    private var nameText: some View {
        Text(order.contactName?.isEmpty == false ? name : name.unbroken).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
    }

    private var metaGrid: some View {
        let cells = [
            ("Order ID", OrderUi.shortId(order)),
            ("Date", Fmt.date(order.createdAt)),
            ("Channel", channelStyle(order.channel.isEmpty ? nil : order.channel).label),
            ("Currency", order.currency.isEmpty ? "KES" : order.currency),
        ]
        return VStack(spacing: 8) {
            ForEach(0..<2, id: \.self) { row in
                HStack(spacing: 8) {
                    ForEach(0..<2, id: \.self) { col in
                        let cell = cells[row * 2 + col]
                        MetaCell(label: cell.0, value: cell.1)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var hubSection: some View {
        box {
            VStack(alignment: .leading, spacing: 8) {
                FlowLayout(spacing: 6, lineSpacing: 4) {
                    Text(order.hubOrderNumber.flatMap { $0.isEmpty ? nil : $0 } ?? "not in hub")
                        .font(NeemaFont.mono(12, medium: true)).foregroundColor(c.gold2)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(c.bg3))
                    if let h = hub { StatusBadge(text: h.label, tone: h.tone) }
                    if let p = order.hubPaymentStatus, !p.isEmpty {
                        Text("Payment: \(p.prefix(1).uppercased() + p.dropFirst())").font(NeemaFont.manrope(12)).foregroundColor(c.textMid)
                    }
                    if let push = order.hubPushStatus, !push.isEmpty, push != "failed" {
                        Text("Push: \(push)").font(NeemaFont.manrope(12)).foregroundColor(c.textDim)
                    }
                }
                if order.hubPushStatus == "failed" {
                    let red = ToneLook.of(.red)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("PUSH FAILED").font(NeemaFont.manrope(10, .bold)).foregroundColor(red.text(c.isDark))
                        Text(order.hubLastError.flatMap { $0.isEmpty ? nil : $0 } ?? "The push to the hub failed")
                            .font(NeemaFont.manrope(12)).foregroundColor(red.text(c.isDark))
                    }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(red.bg(c.isDark)))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(red.border(c.isDark)))
                }
                FlowLayout(spacing: 8, lineSpacing: 8) {
                    if let href = hubHref {
                        WebBtn(label: "Open in hub ↗", variant: .outline) { if let u = URL(string: href) { openURL(u) } }
                    }
                    if let url = publicUrl {
                        WebBtn(label: "Customer's order page ↗", variant: .outline) { if let u = URL(string: url) { openURL(u) } }
                        WebBtn(label: "Copy link", variant: .ghost) {
                            UIPasteboard.general.string = url
                            app.toast("Order link copied", .success)
                        }
                    }
                }
            }
        }
    }

    private var items: some View {
        box {
            VStack(alignment: .leading, spacing: 8) {
                if order.items.isEmpty {
                    Text("No items recorded").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                        .frame(maxWidth: .infinity).padding(.vertical, 8)
                } else {
                    ForEach(Array(order.items.enumerated()), id: \.offset) { _, item in
                        HStack(alignment: .top, spacing: 8) {
                            // The SKU follows the name, or drops under it when the line is full.
                            FlowLayout(spacing: 6, lineSpacing: 2) {
                                Text(item.name).font(NeemaFont.manrope(12, .medium)).foregroundColor(c.text)
                                if let sku = item.sku, !sku.isEmpty {
                                    Text(sku).font(NeemaFont.mono(10)).foregroundColor(c.textDim)
                                }
                            }
                            Spacer(minLength: 8)
                            VStack(alignment: .trailing, spacing: 0) {
                                // A line whose price this build can't read shows its
                                // quantity alone, never a made-up "KES 0".
                                if item.priceKnown {
                                    Text(OrderUi.money(item.lineTotal, order.currency).unbroken).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).monospacedDigit()
                                    Text("\(OrderUi.money(item.effectiveUnit, order.currency).unbroken) × \(OrderUi.qtyText(item.effectiveQty))")
                                        .font(NeemaFont.manrope(10)).foregroundColor(c.textDim).monospacedDigit()
                                } else {
                                    Text("× \(OrderUi.qtyText(item.effectiveQty))").font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).monospacedDigit()
                                }
                            }
                        }
                    }
                }
                // pt-2.5 mt-2 over a #cee6b2 rule
                Hairline(color: c.bg4)
                HStack {
                    Text("Total").font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
                    Spacer()
                    Text(OrderUi.money(order.amount, order.currency).unbroken).font(NeemaFont.manrope(16, .bold)).foregroundColor(c.gold2).monospacedDigit()
                }
                .padding(.top, 2)
            }
        }
    }

    /// The reply Neema sent with the order: amber-600 label, amber-800 text.
    private func noteBox(_ note: String) -> some View {
        let amber = ToneLook.of(.amber)
        return VStack(alignment: .leading, spacing: 4) {
            Text("📝 NOTE").font(NeemaFont.manrope(10, .bold)).tracking(0.25).foregroundColor(c.isDark ? amber.dot : Palette.amber600)
            Text(note).font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? Palette.amber200 : Palette.amber800)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(amber.bg(c.isDark)))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(amber.border(c.isDark)))
    }
}
