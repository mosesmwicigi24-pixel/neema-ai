import SwiftUI
import NeemaCore

/// One order in the list (Android `OrderRow`): avatar, name, channel, status,
/// the hub's number and link, a push failure, phone and items, time, amount.
struct OrderRowView: View {
    let order: Order
    let isUpdating: Bool
    /// A phone (or big text): the amount sits beside the name so the name keeps its room.
    var compact: Bool = false
    /// The order open in the tablet's side pane.
    var highlighted: Bool = false
    let now: Date
    let onTap: () -> Void
    let onPushFailed: () -> Void
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL

    // The HUB is the authority once an order is pushed there; `status` is our
    // own triage flag, and showing it for a linked order is how a confirmed
    // sale kept reading "Pending".
    private var meta: StatusMeta { OrderUi.hubMeta(order) ?? OrderUi.statusMeta(order.status) }
    private var hubHref: String? { OrderUi.hubOrderHref(order) }
    // The web's `contact_name ?? formatPhone(..)` over mapOrder's `contact_name ?? wa_id`:
    // the API sends no contact_name, so the name is the bare wa_id and the
    // formatted phone is the line under it, as on the web.
    private var name: String { order.customerName.isEmpty ? "Unknown" : order.customerName }
    private var summary: (text: String, more: Int) { OrderUi.itemSummary(order) }
    private var ago: String { Fmt.timeAgo(order.createdAt, now: Int64(now.timeIntervalSince1970 * 1000)) }

    var body: some View {
        Button(action: onTap) {
            HStack(alignment: compact ? .top : .center, spacing: 12) {
                AvatarView(name: name, size: 38)
                if compact { compactBody } else { wideBody }
            }
            .padding(.horizontal, 16).padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(highlighted ? (c.isDark ? c.bg3 : Palette.paneHighlight) : Color.clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(name), \(meta.label), \(OrderUi.money(order.amount, order.currency))")
        .accessibilityHint("Opens the order")
    }

    // ── Pieces ────────────────────────────────────────────────────────────────

    /// The REAL hub order number — never a slice of a timestamp.
    private var hubNumber: some View {
        Text(order.hubOrderNumber.flatMap { $0.isEmpty ? nil : $0 } ?? "not in hub")
            .font(NeemaFont.mono(10, medium: true)).foregroundColor(c.gold2).lineLimit(1)
            .padding(.horizontal, 4).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(c.bg3))
    }

    @ViewBuilder private var hubLink: some View {
        if let href = hubHref {
            Button { if let u = URL(string: href) { openURL(u) } } label: {
                Text("Open in hub ↗").font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.gold2).lineLimit(1)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .overlay(RoundedRectangle(cornerRadius: 4).stroke(c.isDark ? c.border : Palette.hubLinkBorder))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open in hub")
        }
    }

    @ViewBuilder private var pushFailed: some View {
        if order.hubPushStatus == "failed" {
            // The web shows the error as a tooltip; a tap reads it out here.
            Button(action: onPushFailed) { StatusBadge(text: "push failed", tone: .red) }
                .buttonStyle(.plain)
                .accessibilityLabel("Push to the hub failed; tap for the reason")
        }
    }

    @ViewBuilder private var summaryText: some View {
        let s = summary
        if !s.text.isEmpty {
            // The separator travels with the summary, so a wrap never leaves it dangling.
            (Text("·  ").foregroundColor(c.isDark ? c.border : Palette.stone200) + Text(s.text + (s.more > 0 ? " +\(s.more) more" : "")))
                .font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? c.textMid : Palette.stone500).lineLimit(1)
        }
    }

    private var amount: some View {
        Text(OrderUi.money(order.amount, order.currency).unbroken).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
            .monospacedDigit().lineLimit(1).multilineTextAlignment(.trailing)
    }

    @ViewBuilder private var spinner: some View {
        if isUpdating { ProgressView().progressViewStyle(.circular).tint(c.gold2).scaleEffect(0.7).frame(width: 16, height: 16) }
    }

    private var compactBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Row 1: name … amount, the figure right-aligned. When both can't
            // fit whole, the amount takes its own line — a phone number is
            // never cut to "+254 711 2…" to make room for it.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    Text(name.unbroken).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).lineLimit(1)
                    Spacer(minLength: 0)
                    spinner
                    amount
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(name.unbroken).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).lineLimit(1)
                    HStack(spacing: 6) { Spacer(minLength: 0); spinner; amount }
                }
            }
            // Row 2: channel, status, hub number, hub link, push failure.
            FlowLayout(spacing: 6, lineSpacing: 4) {
                if !order.channel.isEmpty { OrderChannelPill(channel: order.channel) }
                StatusBadge(text: meta.label, tone: meta.tone)
                hubNumber
                hubLink
                pushFailed
            }
            .padding(.top, 4)
            // Row 3: phone and the items, one line.
            let phone = OrderUi.phoneLine(order, displayedName: name)
            if phone != nil || !summary.text.isEmpty {
                HStack(spacing: 6) {
                    if let p = phone { Text(p.unbroken).font(NeemaFont.mono(12)).foregroundColor(c.textDim).lineLimit(1) }
                    summaryText
                }
                .padding(.top, 4)
            }
            // Row 4: time
            Text(ago).font(NeemaFont.manrope(10)).foregroundColor(c.textDim).padding(.top, 2)
        }
    }

    private var wideBody: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 0) {
                // Row 1: name + channel + status
                FlowLayout(spacing: 8, lineSpacing: 3) {
                    Text(name).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).lineLimit(1)
                    if !order.channel.isEmpty { OrderChannelPill(channel: order.channel) }
                    StatusBadge(text: meta.label, tone: meta.tone)
                }
                // Row 2: hub order number, hub link, push failure, phone, items
                FlowLayout(spacing: 6, lineSpacing: 3) {
                    hubNumber
                    hubLink
                    pushFailed
                    if let p = OrderUi.phoneLine(order, displayedName: name) {
                        Text(p).font(NeemaFont.mono(12)).foregroundColor(c.textDim)
                    }
                    summaryText.frame(maxWidth: 232, alignment: .leading)
                }
                .padding(.top, 3)
                // Row 3: time
                Text(ago).font(NeemaFont.manrope(10)).foregroundColor(c.textDim).padding(.top, 2)
            }
            Spacer(minLength: 12)
            VStack(alignment: .trailing, spacing: 2) {
                amount
                Text(order.currency.isEmpty ? "KES" : order.currency).font(NeemaFont.manrope(10)).foregroundColor(c.textDim)
                spinner.padding(.top, 2)
            }
        }
    }
}
