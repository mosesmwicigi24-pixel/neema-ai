import SwiftUI
import UIKit
import NeemaCore

// ── WhatsApp calling (manage_settings) ────────────────────────────────────────

/// Settings → WhatsApp calling (CALLING_UX.md §2.1; Android
/// `WhatsAppCallingCard`): callback permission, the call button, voicemail,
/// weekly call hours and holidays, Meta's restrictions (read only), and the
/// call-request template. Save sends only what changed; each field says what
/// is wrong with it before anything is sent.
struct WhatsAppCallingCard: View {
    let m: CallingSettingsModel
    let u: CallingSettingsUi
    @Environment(\.neema) private var c

    var body: some View {
        let red = c.isDark ? Palette.red300 : Palette.red700
        let green = c.isDark ? Palette.emerald300 : Palette.emerald700
        SettingsCard(title: "WhatsApp calling",
                     description: "How customers reach this number by WhatsApp call, and when. Changes can take up to 7 days to reach customers' phones.") {
            if let why = u.loadError {
                LoadProblem(message: why, title: "Couldn't load the calling settings", retrying: u.loading, onRetry: { m.load() })
                    .padding(.bottom, 10)
            }
            if u.draft == nil && u.loadError == nil {
                Text("Loading…").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
            }
            if let d = u.draft {
                draftBody(d, red: red, green: green)
            }
            Hairline(color: c.isDark ? c.border : c.hairline).padding(.vertical, 14)
            CallTemplateStatus(u: u, red: red, green: green) { m.createTemplate() }
        }
        // Read as the card first appears (not a frame later): with an answer on hand it shows at once.
        .onAppear { m.start() }
    }

    @ViewBuilder
    private func draftBody(_ d: CallingSettings, red: Color, green: Color) -> some View {
        let vmOn = d.voicemail?.status == "ENABLED"
        let hours = d.callHours
        let hoursOn = hours?.status == "ENABLED"
        Group {
        // Meta's restrictions: read only — they lift by themselves (up to 7 days).
        if !d.restrictions.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                Text("WhatsApp restricts calling on this number").font(NeemaFont.manrope(12, .semibold)).foregroundColor(red)
                ForEach(Array(d.restrictions.enumerated()), id: \.offset) { _, r in
                    Text(CallingSettingsModel.restrictionWords(r)).font(NeemaFont.manrope(12)).foregroundColor(c.textMid).fixedSize(horizontal: false, vertical: true)
                }
                Text("Calls you place may fail until it lifts.").font(NeemaFont.manrope(11)).foregroundColor(c.muted).padding(.top, 2)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(red.opacity(0.1)))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(red.opacity(0.3)))
            .padding(.bottom, 12)
        }
        if u.changedElsewhere {
            HStack(alignment: .center, spacing: 8) {
                Text("WhatsApp says these settings changed.").font(NeemaFont.manrope(12)).foregroundColor(c.textMid)
                    .frame(maxWidth: .infinity, alignment: .leading)
                TextLink(label: "Reload", size: 13) { m.discard(); m.load() }
            }
            .padding(.bottom, 8)
        }
        }
        CallingToggle(title: "Call back customers who called",
                      explanation: "When a customer calls this number, WhatsApp lets your team call them back for 7 days without sending a call request.",
                      checked: d.callbackPermissionStatus == "ENABLED") { on in
            m.edit { var x = $0; x.callbackPermissionStatus = on ? "ENABLED" : "DISABLED"; return x }
        }
        SettingsField(label: "Call button in WhatsApp") {
            FlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(Array(Self.ICON_CHOICES.enumerated()), id: \.offset) { _, choice in
                    SettingsChipButton(label: choice.label, selected: (d.callIconVisibility ?? "DEFAULT") == choice.value) {
                        m.edit { var x = $0; x.callIconVisibility = choice.value; return x }
                    }
                }
            }
        }
        CallingToggle(title: "Voicemail", explanation: "A caller nobody answers can leave a voice message — it arrives in their chat.", checked: vmOn) { on in
            m.edit { var x = $0; var v = x.voicemail ?? CallVoicemail(); v.status = on ? "ENABLED" : "DISABLED"; x.voicemail = v; return x }
        }
        if vmOn {
            let err = u.fieldErrors["voicemail.timeout"]
            SettingsField(label: "Ring for (seconds) before voicemail", hint: err ?? "0–30 seconds.", hintColor: err != nil ? red : nil) {
                SettingsInput(text: Binding(get: { d.voicemail?.timeoutSeconds.map(String.init) ?? "" }, set: { t in
                    let digits = String(t.filter { $0.isASCII && $0.isNumber }.prefix(3))
                    m.edit { var x = $0; var v = x.voicemail ?? CallVoicemail(); v.timeoutSeconds = Int(digits); x.voicemail = v; return x }
                }), keyboard: .numberPad, isError: err != nil)
                .frame(width: 120)
            }
        }
        CallingToggle(title: "Call hours", explanation: "Outside these hours WhatsApp tells callers you're closed.", checked: hoursOn) { on in
            m.edit { var x = $0; var h = x.callHours ?? CallHours(timezoneId: "Africa/Nairobi"); h.status = on ? "ENABLED" : "DISABLED"; x.callHours = h; return x }
        }
        if hoursOn, let h = hours {
            CallHoursEditor(h: h, errors: u.fieldErrors, red: red) { change in
                m.edit { var x = $0; if let cur = x.callHours { x.callHours = change(cur) }; return x }
            }
        }
        Group {
            Spacer().frame(height: 6)
            FlowLayout(spacing: 10, lineSpacing: 6) {
                SettingsSaveButton(label: "Save calling settings", saving: u.saving, enabled: u.dirty) { m.save() }
                if u.dirty && !u.saving { TextLink(label: "Discard changes", size: 13) { m.discard() } }
            }
            if let e = u.saveError {
                Text(e).font(NeemaFont.manrope(12)).foregroundColor(red).fixedSize(horizontal: false, vertical: true).padding(.top, 6)
            }
            if !u.fieldErrors.isEmpty {
                Text("Fix the fields marked above — nothing was sent.").font(NeemaFont.manrope(12)).foregroundColor(red).padding(.top, 6)
            }
            if u.saved {
                Text("Saved — customers may take up to 7 days to see the change.").font(NeemaFont.manrope(12)).foregroundColor(green).padding(.top, 6)
            }
        }
    }

    private static let ICON_CHOICES: [(value: String, label: String)] = [("DEFAULT", "Show"), ("HIDE_IN_CHAT", "Hide in chats"), ("DISABLE_ALL", "Hide everywhere")]
}

/// A titled switch with its explanation, the whole row the target.
struct CallingToggle: View {
    let title: String
    let explanation: String
    let checked: Bool
    let onChange: (Bool) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Toggle(isOn: Binding(get: { checked }, set: { onChange($0) })) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(NeemaFont.manrope(13, .semibold)).foregroundColor(c.text)
                Text(explanation).font(NeemaFont.manrope(11)).foregroundColor(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            .padding(.trailing, 8)
        }
        .tint(c.gold)
        .frame(minHeight: 48)
        .padding(.bottom, 12)
    }
}

/// The weekly hours (one opening per day) and the holidays.
struct CallHoursEditor: View {
    let h: CallHours
    let errors: [String: String]
    let red: Color
    let edit: ((CallHours) -> CallHours) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let tzErr = errors["hours.timezone"]
        SettingsField(label: "Time zone", hint: tzErr, hintColor: red) {
            SettingsInput(text: Binding(get: { h.timezoneId ?? "" }, set: { t in
                edit { var x = $0; let v = t.trimmingCharacters(in: .whitespaces); x.timezoneId = v.isEmpty ? nil : v; return x }
            }), placeholder: "Africa/Nairobi", isError: tzErr != nil)
        }
        Text("Open").font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textMid)
        ForEach(Array(CallingSettingsModel.DAYS.enumerated()), id: \.offset) { _, day in dayRow(day) }
        Spacer().frame(height: 10)
        Text("Holidays (closed)").font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textMid)
        if let e = errors["holidays"] { Text(e).font(NeemaFont.manrope(11)).foregroundColor(red) }
        ForEach(Array(h.holidays.enumerated()), id: \.offset) { i, x in holidayRow(i, x) }
        if h.holidays.count < 20 {
            Button {
                edit { var x = $0; x.holidays.append(CallHoliday(date: "", startTime: "0000", endTime: "2359")); return x }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "plus").font(.system(size: 13, weight: .semibold))
                    Text("Add holiday").font(NeemaFont.manrope(13, .semibold))
                }
                .foregroundColor(c.gold).frame(minHeight: 48).padding(.horizontal, 8).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        Spacer().frame(height: 6)
    }

    /// "MONDAY" → "Mon".
    private func dayLabel(_ day: String) -> String { String(String(day.prefix(1) + day.dropFirst().lowercased()).prefix(3)) }

    private func toggleDay(_ day: String, on: Bool) {
        edit { cur in
            var x = cur
            if on { x.weekly.append(CallHoursSlot(dayOfWeek: day, openTime: "0900", closeTime: "1700")) }
            else { x.weekly.removeAll { $0.dayOfWeek == day } }
            return x
        }
    }

    private func setSlot(_ day: String, open: String? = nil, close: String? = nil) {
        edit { cur in
            var x = cur
            var done = false
            x.weekly = x.weekly.map { s in
                guard s.dayOfWeek == day, !done else { return s }
                done = true
                var t = s
                if let o = open { t.openTime = o }
                if let cl = close { t.closeTime = cl }
                return t
            }
            return x
        }
    }

    private func timeField(_ value: String, placeholder: String, isError: Bool, onChange: @escaping (String) -> Void) -> some View {
        SettingsInput(text: Binding(get: { value }, set: onChange), placeholder: placeholder, keyboard: .numbersAndPunctuation, isError: isError)
            .frame(width: 92)
    }

    private func dayRow(_ day: String) -> some View {
        let slot = h.weekly.first { $0.dayOfWeek == day }
        let err = errors["hours.\(day)"]
        return VStack(alignment: .leading, spacing: 2) {
            FlowLayout(spacing: 8, lineSpacing: 4) {
                Button { toggleDay(day, on: slot == nil) } label: {
                    HStack(spacing: 8) {
                        Image(systemName: slot != nil ? "checkmark.square.fill" : "square").font(.system(size: 20)).foregroundColor(slot != nil ? c.gold : c.muted)
                        Text(dayLabel(day)).font(NeemaFont.manrope(13)).foregroundColor(c.text)
                    }
                    .frame(width: 128, height: 48, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(slot != nil ? AccessibilityTraits.isSelected : AccessibilityTraits())
                if let s = slot {
                    timeField(CallingSettingsModel.showTime(s.openTime), placeholder: "09:00", isError: err != nil) { t in setSlot(day, open: CallingSettingsModel.readTime(t)) }
                    timeField(CallingSettingsModel.showTime(s.closeTime), placeholder: "17:00", isError: err != nil) { t in setSlot(day, close: CallingSettingsModel.readTime(t)) }
                } else {
                    Text("Closed").font(NeemaFont.manrope(12)).foregroundColor(c.muted).frame(height: 48)
                }
            }
            if let e = err { Text(e).font(NeemaFont.manrope(11)).foregroundColor(red) }
        }
        .padding(.top, 4)
    }

    private func setHoliday(_ i: Int, _ f: @escaping (CallHoliday) -> CallHoliday) {
        edit { cur in
            var x = cur
            x.holidays = x.holidays.enumerated().map { j, y in j == i ? f(y) : y }
            return x
        }
    }

    private func holidayRow(_ i: Int, _ x: CallHoliday) -> some View {
        let err = errors["holiday.\(i)"]
        return VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .center, spacing: 6) {
                SettingsInput(text: Binding(get: { x.date ?? "" }, set: { t in setHoliday(i) { var y = $0; y.date = t.trimmingCharacters(in: .whitespaces); return y } }),
                              placeholder: "2026-12-25", keyboard: .numbersAndPunctuation, isError: err != nil)
                    .frame(maxWidth: .infinity)
                    .layoutPriority(1)
                SettingsInput(text: Binding(get: { CallingSettingsModel.showTime(x.startTime) }, set: { t in setHoliday(i) { var y = $0; y.startTime = CallingSettingsModel.readTime(t); return y } }),
                              placeholder: "00:00", keyboard: .numbersAndPunctuation, isError: err != nil)
                    .frame(width: 84)
                SettingsInput(text: Binding(get: { CallingSettingsModel.showTime(x.endTime) }, set: { t in setHoliday(i) { var y = $0; y.endTime = CallingSettingsModel.readTime(t); return y } }),
                              placeholder: "23:59", keyboard: .numbersAndPunctuation, isError: err != nil)
                    .frame(width: 84)
                Button {
                    edit { cur in var z = cur; z.holidays = z.holidays.enumerated().filter { $0.offset != i }.map { $0.element }; return z }
                } label: {
                    Image(systemName: "xmark").font(.system(size: 14, weight: .medium)).foregroundColor(c.muted).frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Remove holiday \(x.date ?? "")")
            }
            if let e = err { Text(e).font(NeemaFont.manrope(11)).foregroundColor(red) }
        }
        .padding(.top, 4)
    }
}

/// The call-request template WhatsApp needs outside the 24 h window: whether it's there, approved, and a Create.
struct CallTemplateStatus: View {
    let u: CallingSettingsUi
    let red: Color
    let green: Color
    let onCreate: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let t = u.template
        let status = statusLine(t)
        VStack(alignment: .leading, spacing: 0) {
            Text("Call-request template").font(NeemaFont.manrope(13, .semibold)).foregroundColor(c.text)
            Text("A customer who hasn't messaged in 24 hours can only be asked for call permission with an approved template.")
                .font(NeemaFont.manrope(11)).foregroundColor(c.muted).fixedSize(horizontal: false, vertical: true)
            Spacer().frame(height: 6)
            if let line = status.line {
                Text(line).font(NeemaFont.manrope(12)).foregroundColor(status.tone).fixedSize(horizontal: false, vertical: true)
            }
            if let e = u.templateError {
                Text(e).font(NeemaFont.manrope(12)).foregroundColor(red).fixedSize(horizontal: false, vertical: true)
            }
            if canCreate(t) {
                Spacer().frame(height: 8)
                SettingsSaveButton(label: "Create template", saving: u.templateBusy, action: onCreate)
            }
        }
    }

    private func canCreate(_ t: PermissionTemplate?) -> Bool {
        guard let t = t, t.wabaConfigured else { return false }
        return t.exists == false || !t.configured || t.status == "rejected"
    }

    private func statusLine(_ t: PermissionTemplate?) -> (line: String?, tone: Color) {
        guard let t = t else { return (u.templateError == nil ? "Checking…" : nil, c.muted) }
        if !t.wabaConfigured { return ("The server needs WABA_BUSINESS_ACCOUNT_ID set before a template can be created.", c.textMid) }
        let name = t.name ?? ""
        if t.status == "approved" { return ("Approved — \(name) (\(t.language ?? ""))", green) }
        if t.status == "pending" || t.status == "in_appeal" { return ("Waiting for WhatsApp to approve \(name)", c.textMid) }
        if t.status == "rejected" { return ("WhatsApp rejected \(name) — create it again with different wording", red) }
        if t.exists == false || !t.configured { return ("Not created yet — requests outside 24 hours can't be sent", c.textMid) }
        if t.exists == nil { return ("Couldn't check with WhatsApp just now", c.textMid) }
        return ("\(name): \(t.status ?? "unknown")", c.textMid)
    }
}

// ── App crash reports (manage_settings) ───────────────────────────────────────

/// The phone apps' crash reports, as the server keeps them: what failed, on
/// which device and build, and the full trace — selectable, with a Copy that
/// puts it on the clipboard to send on. Loaded on tap only (admins: the
/// server's manage_settings), so Settings itself never waits on it.
struct CrashReportsCard: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @State private var reports: [ClientCrashReport]? = nil
    @State private var loading = false
    @State private var error: String? = nil
    @SceneStorage("settings.crash.open") private var open: String = ""

    var body: some View {
        SettingsCard(title: "App crash reports",
                     description: "When the app closes on someone, it sends what went wrong here. Copy a report and send it on to get it fixed.") {
            TextLink(label: loading ? "Loading…" : (reports == nil ? "Show crash reports" : "Refresh"), size: 13) { load() }
                .disabled(loading)
            if let e = error {
                Text(e).font(NeemaFont.manrope(12)).foregroundColor(c.red).fixedSize(horizontal: false, vertical: true)
            }
            if let list = reports, list.isEmpty {
                Text("No crash reports — nothing has closed on anyone.").font(NeemaFont.manrope(12)).foregroundColor(c.textDim)
            }
            if let list = reports {
                ForEach(list) { r in row(r) }
            }
            // The newest report on this phone, delivered or not (Android's "On this phone").
            if let mine = app.container.crashVault.latest() {
                VStack(alignment: .leading, spacing: 4) {
                    Text("ON THIS PHONE").font(NeemaFont.manrope(10, .semibold)).tracking(1).foregroundColor(c.muted)
                    Text(mine.summary.trimmingCharacters(in: .whitespaces).isEmpty ? mine.kind : mine.summary)
                        .font(NeemaFont.manrope(13, .medium)).foregroundColor(c.text).lineLimit(3)
                    Text([mine.at, mine.kind, mine.device, mine.sdk > 0 ? "iOS \(mine.sdk)" : nil, "build \(mine.build)"].compactMap { $0 }.joined(separator: " · "))
                        .font(NeemaFont.manrope(11)).foregroundColor(c.muted)
                    TextLink(label: "Copy report", size: 13) {
                        UIPasteboard.general.string = CrashVault.asText(mine)
                        app.toast("Crash report copied")
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
                .padding(.top, 8)
            }
        }
    }

    private func load() {
        if loading { return }
        loading = true
        error = nil
        let api = app.container.api
        Task { @MainActor in
            do {
                reports = try await api.crashes.list(limit: 20)
            } catch {
                if !SalesErrors.isCancellation(error) { self.error = "Couldn't load the crash reports. \(FriendlyErrors.text(of: error))" }
            }
            loading = false
        }
    }

    private func meta(_ r: ClientCrashReport) -> String {
        let parts: [String?] = [
            (r.at ?? r.receivedAt).map { Fmt.timeAgo($0) },
            r.agentName,
            r.device,
            r.sdk.flatMap { $0 > 0 ? "Android API \($0)" : nil },
            r.build.map { "build \($0)" },
            r.kind != "crash" ? r.kind : nil,
        ]
        return parts.compactMap { $0 }.joined(separator: " · ")
    }

    private func copyText(_ r: ClientCrashReport) -> String {
        let line: [String?] = [r.at, r.device, r.sdk.map { "API \($0)" }, r.appVersion, r.build]
        return r.summary + "\n" + line.compactMap { $0 }.joined(separator: " · ") + "\n" + r.trace
    }

    private func row(_ r: ClientCrashReport) -> some View {
        let expanded = open == r.id
        return VStack(alignment: .leading, spacing: 0) {
            Button { open = expanded ? "" : r.id } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(r.summary.trimmingCharacters(in: .whitespaces).isEmpty ? r.kind : r.summary)
                        .font(NeemaFont.manrope(13, .medium)).foregroundColor(c.text).lineLimit(expanded ? 6 : 2).multilineTextAlignment(.leading)
                    Text(meta(r)).font(NeemaFont.manrope(11)).foregroundColor(c.muted).multilineTextAlignment(.leading)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if expanded {
                ScrollView([.horizontal, .vertical]) {
                    Text(r.trace).font(NeemaFont.mono(11)).foregroundColor(c.textDim).textSelection(.enabled)
                        .fixedSize(horizontal: true, vertical: true)
                }
                .frame(maxHeight: 320)
                .padding(.top, 8)
                HStack(spacing: 4) {
                    TextLink(label: "Copy report", size: 13) {
                        UIPasteboard.general.string = copyText(r)
                        app.toast("Crash report copied")
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
        .padding(.top, 8)
    }
}
