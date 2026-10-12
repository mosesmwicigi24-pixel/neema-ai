import SwiftUI

/// A detail that fits the window (Android `AdaptiveSheet`): under 600 pt the
/// phone's bottom sheet (full height, the system drag indicator, a title bar
/// with ✕ unless the detail brings its own); from 600 pt a panel sliding in
/// from the end edge — `panelWidth` or `maxFraction` of the window — so a
/// product or a lead opens beside the list instead of a phone sheet rising
/// across an iPad. A swipe, a tap outside and the close control all dismiss
/// it; dismissing clears `item`.
struct AdaptiveSheet<Item: Equatable, Detail: View>: ViewModifier {
    @Binding var item: Item?
    /// The window's width (the screen's GeometryReader).
    let width: CGFloat
    var panelWidth: CGFloat = 440
    var maxFraction: CGFloat = 0.9
    /// The phone sheet's title bar; off when the detail has its own header.
    var titleBar: Bool = true
    let title: (Item) -> String
    @ViewBuilder let detail: (Item) -> Detail
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private var wide: Bool { width >= 600 }

    private var panelOpen: Binding<Bool> {
        Binding(get: { wide && item != nil }, set: { if !$0 { item = nil } })
    }

    private var sheetOpen: Binding<Bool> {
        Binding(get: { !wide && item != nil }, set: { if !$0 { item = nil } })
    }

    func body(content: Content) -> some View {
        content
            .overlay {
                if wide {
                    SideSheet(open: panelOpen, width: min(panelWidth, width * maxFraction), title: item.map(title) ?? "") {
                        if let i = item { detail(i) }
                    }
                }
            }
            .sheet(isPresented: sheetOpen) {
                if let i = item {
                    VStack(spacing: 0) {
                        if titleBar { ModalTitleBar(title: title(i), onClose: { item = nil }).padding(.top, 16) }
                        detail(i)
                    }
                    .background(c.bg2)
                    .environment(\.neema, c)
                    .environmentObject(app)
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
                }
            }
    }
}

extension View {
    /// Presents `item`'s detail as a bottom sheet on a phone or an end-edge panel on a wider window.
    func adaptiveSheet<Item: Equatable, Detail: View>(
        item: Binding<Item?>, width: CGFloat, panelWidth: CGFloat = 440, maxFraction: CGFloat = 0.9, titleBar: Bool = true,
        title: @escaping (Item) -> String, @ViewBuilder detail: @escaping (Item) -> Detail
    ) -> some View {
        modifier(AdaptiveSheet(item: item, width: width, panelWidth: panelWidth, maxFraction: maxFraction, titleBar: titleBar, title: title, detail: detail))
    }
}
