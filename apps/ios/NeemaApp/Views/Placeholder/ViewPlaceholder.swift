import SwiftUI
import NeemaCore

/// Stands in for a screen until its cycle lands it.
struct ViewPlaceholder: View {
    let view: ViewId
    let cycle: Int
    let note: String
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(view.label).font(NeemaFont.headlineSmall).foregroundColor(c.text)
            Text(note).font(NeemaFont.bodyMedium).foregroundColor(c.textMid)
            Text("Coming in cycle \(cycle).").font(NeemaFont.labelMedium).foregroundColor(c.textDim).padding(.top, 8)
            Spacer()
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(c.surface)
    }
}
