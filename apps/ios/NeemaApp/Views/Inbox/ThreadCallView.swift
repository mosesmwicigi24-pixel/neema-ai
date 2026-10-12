import SwiftUI
import NeemaCore

/// Which app a call was on — a badge, so a mixed history is never ambiguous (Android `CallChannelBadge`).
struct CallChannelBadge: View {
    let channel: String?
    let onDark: Bool
    var fontSize: CGFloat = 11

    var body: some View {
        let m = channelOf(channel) == CallWords.MESSENGER
        let fg: Color = m ? (onDark ? Color(hex: 0x9CCBFF) : Palette.ink) : (onDark ? Color(hex: 0x7EE2A8) : Color(hex: 0x128C4B))
        let bg: Color = m ? (onDark ? Color(hex: 0x0084FF, alpha: 0.18) : Color(hex: 0xEAF3FF)) : (onDark ? Color(hex: 0x25D366, alpha: 0.14) : Color(hex: 0xE7F6EC))
        let label = channelLabel(channel)
        HStack(spacing: 3) {
            if let d = ChannelIcons.of(m ? "messenger" : "whatsapp") {
                SVGIcon(d: d, size: fontSize + 1).foregroundColor(m ? ChannelColors.messenger : fg)
            }
            Text(label).font(NeemaFont.manrope(fontSize, .semibold)).foregroundColor(fg).lineLimit(1)
        }
        .padding(.leading, 3).padding(.trailing, 6).padding(.vertical, 1)
        .background(Capsule().fill(bg))
        .accessibilityLabel(label)
    }
}

/// The direction glyph beside a call's word (SF Symbols for the web's arrows).
struct CallDirGlyph: View {
    let icon: CallDirIcon?
    let color: Color
    var size: CGFloat = 13
    var body: some View {
        Image(systemName: {
            switch icon {
            case .out: return "arrow.up.right"
            case .in: return "arrow.down.left"
            case .missed: return "phone.down"
            case .back: return "arrow.uturn.left"
            case nil: return "phone"
            }
        }())
        .font(.system(size: size, weight: .semibold))
        .foregroundColor(color)
    }
}

/// A WhatsApp call in the thread, where it happened (CALLING_UX.md §7): a
/// centred pill — incoming / outgoing / missed icon, the server's label
/// ("Incoming call · 4:12", "Missed call"), who took it, the time — and, when
/// the call was summarised, a card under it: the summary, the next action and
/// "Use as reply", which puts the AI's follow-up in the composer (never sends).
struct ThreadCallEventView: View {
    let msg: ThreadMsg
    let onUseAsReply: (String) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let call = msg.call
        let words = call.map { callRowWords($0) }
        let tone: Color = {
            switch words?.tone {
            case .bad: return c.isDark ? Palette.red300 : Palette.red700
            case .warn: return c.isDark ? Palette.amber300 : Palette.amber700
            case .live, .good: return c.isDark ? Palette.emerald300 : Palette.emerald700
            default: return c.textMid
            }
        }()
        // A voicemail came with it: "Missed call · voicemail" (the audio is a message in this chat).
        let label = threadCallLabel(msg.body, call)
        // Who took it — not for calls nobody answered (as the web's pill).
        let unanswered: Set<String> = ["missed", "no_answer", "cancelled", "failed"]
        let agent = agentFirst(msg.agentName ?? call?.agentName).flatMap { a -> String? in unanswered.contains(call?.status ?? "") ? nil : a }
        let time = (call?.startedAt ?? msg.createdAt).map { Fmt.time($0) } ?? ""
        let rest = [agent, time.isEmpty ? nil : time].compactMap { $0 }.joined(separator: " · ")
        let line = ([label] + [agent, time.isEmpty ? nil : time].compactMap { $0 }).joined(separator: " · ")
        VStack(spacing: 6) {
            HStack(spacing: 6) {
                CallDirGlyph(icon: words?.icon, color: tone)
                CallChannelBadge(channel: call?.channel, onDark: c.isDark, fontSize: 10)
                Text(label).font(NeemaFont.manrope(11, .semibold)).foregroundColor(tone).lineLimit(1)
                if !rest.isEmpty { Text(" · \(rest)").font(NeemaFont.manrope(11)).foregroundColor(c.textMid).lineLimit(1) }
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(Capsule().fill(c.isDark ? c.bg3 : Palette.stone100))
            .overlay(Capsule().stroke(c.isDark ? c.border : Palette.stone200))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(channelLabel(call?.channel)) call: \(line)")
            let summary = (call?.summary ?? msg.eventReason)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let insights = call?.insights
            let facts: [(String, [String])] = [("Products", insights?.products ?? []), ("Objections", insights?.objections ?? []), ("Commitments", insights?.commitments ?? [])].filter { !$0.1.isEmpty }
            let followUp = insights?.followUpMessage?.trimmingCharacters(in: .whitespacesAndNewlines)
            if (summary?.isEmpty == false) || insights?.nextAction != nil || (followUp?.isEmpty == false) || !facts.isEmpty {
                CallSummaryCard(summary: summary?.isEmpty == true ? nil : summary, nextAction: insights?.nextAction, facts: facts, followUp: followUp?.isEmpty == true ? nil : followUp, onUseAsReply: onUseAsReply)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 4)
    }
}

/// The web's CallPill card: the summary (three lines, then "Show more"), the
/// next action, products / objections / commitments, and the suggested reply
/// — shown in full, so the agent sees what "Use as reply" puts in the box.
private struct CallSummaryCard: View {
    let summary: String?
    let nextAction: String?
    let facts: [(String, [String])]
    let followUp: String?
    let onUseAsReply: (String) -> Void
    @Environment(\.neema) private var c
    @State private var more = false
    @State private var used = false

    var body: some View {
        let green = c.isDark ? Palette.emerald300 : Palette.emerald700
        VStack(alignment: .leading, spacing: 0) {
            Text("CALL SUMMARY").font(NeemaFont.manrope(10, .semibold)).tracking(0.6).foregroundColor(green)
            if let s = summary {
                let long = s.count > 220
                Spacer().frame(height: 4)
                Text(s).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(c.text).lineLimit(long && !more ? 3 : nil)
                if long {
                    Button { more.toggle() } label: {
                        Text(more ? "Show less" : "Show more").font(NeemaFont.manrope(11, .semibold)).foregroundColor(green).frame(minHeight: 32)
                    }
                }
            }
            if let n = nextAction {
                Spacer().frame(height: 6)
                (Text("Next: ").bold() + Text(n)).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(c.text)
            }
            if !facts.isEmpty { Spacer().frame(height: 6) }
            ForEach(facts, id: \.0) { k, v in
                (Text("\(k): ").bold().foregroundColor(c.textMid) + Text(v.joined(separator: " · "))).font(NeemaFont.manrope(11)).lineSpacing(3).foregroundColor(c.text)
            }
            if let reply = followUp {
                Spacer().frame(height: 8)
                VStack(alignment: .leading, spacing: 2) {
                    Text("SUGGESTED REPLY").font(NeemaFont.manrope(10, .semibold)).tracking(0.6).foregroundColor(c.textMid)
                    Text(reply).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(c.text).textSelection(.enabled)
                    Spacer().frame(height: 6)
                    HStack(spacing: 8) {
                        Button { onUseAsReply(reply); used = true } label: {
                            Text("Use as reply").font(NeemaFont.manrope(12, .semibold)).foregroundColor(.white)
                                .padding(.horizontal, 12).padding(.vertical, 9)
                                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Palette.replyGreen))
                        }
                        .frame(minHeight: 48)
                        .accessibilityLabel("Put the suggested reply in the message box")
                        Text(used ? "In the reply box — edit, then send" : "Goes in the reply box — not sent").font(NeemaFont.manrope(11)).foregroundColor(c.textMid)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10).padding(.vertical, 8)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? Color.white.opacity(0.05) : Palette.suggestedReplyBg))
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: 560, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.isDark ? ChannelColors.whatsApp.opacity(0.08) : .white))
        .roundedBorder(c.isDark ? ChannelColors.whatsApp.opacity(0.3) : Palette.emerald100, radius: 12)
        .accessibilityLabel("Call summary")
    }
}
