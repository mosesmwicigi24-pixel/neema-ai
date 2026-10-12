import SwiftUI
import NeemaCore

/// Tap a card for the whole product: every variant with its KES and USD price
/// and all aliases. Read-only, like everything on this screen (Android `ProductDetail`).
struct ProductDetailView: View {
    let item: CatalogItem
    @Environment(\.neema) private var c

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 14) {
                    RoundedRectangle(cornerRadius: 12, style: .continuous).fill(categoryGradient(item.rawCategory, dark: c.isDark))
                        .frame(width: 96, height: 96)
                        .overlay(ProductThumb(item: item, glyphSize: 40))
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.name).font(NeemaFont.manrope(17, .bold)).foregroundColor(c.text)
                        Text("\(CatalogRules.glyph(item.rawCategory)) \(item.category)").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                        StockBadge(item: item).padding(.top, 6)
                    }
                }
                Text(CatalogRules.unbroken(CatalogRules.priceText(item))).font(NeemaFont.manrope(20, .extrabold)).foregroundColor(c.gold2).monospacedDigit().padding(.top, 14)
                if let unit = item.unit, !unit.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text("per \(unit)").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                }
                if item.priceUsd != nil || item.priceKes != nil {
                    Text([item.priceKes.map { Fmt.currency($0) }, item.priceUsd.map { CatalogRules.usd($0) }].compactMap { $0 }.joined(separator: "  ·  "))
                        .font(NeemaFont.manrope(12)).foregroundColor(c.textDim).padding(.top, 2)
                }
                if let d = item.description, !d.isEmpty {
                    Text(d).font(NeemaFont.manrope(13)).foregroundColor(c.text).padding(.top, 12)
                }
                if !item.variants.isEmpty {
                    Text("\(item.variants.count) VARIANTS").font(NeemaFont.manrope(11, .bold)).tracking(0.6).foregroundColor(c.muted).padding(.top, 16).padding(.bottom, 6)
                    ForEach(Array(item.variants.enumerated()), id: \.offset) { _, v in
                        HStack(alignment: .center, spacing: 8) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(v.label ?? v.name ?? v.sku ?? "—").font(NeemaFont.manrope(13, .medium)).foregroundColor(c.text)
                                let attrs = v.attributes.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value)" }.joined(separator: " · ")
                                if !attrs.isEmpty { Text(attrs).font(NeemaFont.manrope(11)).foregroundColor(c.muted) }
                                if let sku = v.sku, !sku.isEmpty { Text(sku).font(NeemaFont.mono(10)).foregroundColor(c.muted) }
                            }
                            Spacer(minLength: 8)
                            VStack(alignment: .trailing, spacing: 1) {
                                Text(v.priceKes.map { Fmt.currency($0) } ?? "—").font(NeemaFont.manrope(13, .semibold)).foregroundColor(c.text).monospacedDigit()
                                if let usd = v.priceUsd { Text(CatalogRules.usd(usd)).font(NeemaFont.manrope(11)).foregroundColor(c.textDim).monospacedDigit() }
                            }
                        }
                        .padding(.vertical, 6)
                        Hairline(color: c.bg3)
                    }
                }
                if !item.aliases.isEmpty {
                    Text("ALIASES").font(NeemaFont.manrope(11, .bold)).tracking(0.6).foregroundColor(c.muted).padding(.top, 16).padding(.bottom, 6)
                    FlowLayout(spacing: 4, lineSpacing: 4) {
                        ForEach(item.aliases, id: \.self) { AliasChip(text: $0) }
                    }
                }
                HStack {
                    Text(item.sku).font(NeemaFont.mono(11)).foregroundColor(c.muted)
                    Spacer()
                    if let id = item.hubProductId { Text("#\(id)").font(NeemaFont.mono(11)).foregroundColor(c.muted) }
                }
                .padding(.top, 16)
                if let t = item.productType { Text("Type: \(t)").font(NeemaFont.manrope(11)).foregroundColor(c.muted) }
                if let u = item.updatedAt { Text("Updated \(Fmt.timeAgo(u))").font(NeemaFont.manrope(11)).foregroundColor(c.muted) }
                if item.isHub {
                    HStack(spacing: 6) {
                        Image(systemName: "lock").font(.system(size: 12)).foregroundColor(c.muted)
                        Text("Maintained in the hub — to change this product, edit it in the hub.").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                    }
                    .padding(.top, 16)
                }
            }
            .padding(.horizontal, 20).padding(.bottom, 28).padding(.top, 8)
        }
    }
}
