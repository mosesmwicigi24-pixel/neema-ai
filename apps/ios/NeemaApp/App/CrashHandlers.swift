import Foundation
import UIKit
import NeemaCore

/// The app's crash handlers (Android `CrashVault.install`): an uncaught
/// exception on any thread and the fatal signals are written to the vault
/// first, then the process ends as it would have (continuing after an
/// unknown failure is worse than restarting). Installed first thing at
/// launch; the vault's directory is Application Support/crash.
enum CrashHandlers {
    nonisolated(unsafe) private static var vault: CrashVault?
    private static let signals: [Int32] = [SIGABRT, SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGTRAP]

    static func vaultDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("crash")
    }

    static func install(_ v: CrashVault) {
        vault = v
        let info = Bundle.main.infoDictionary ?? [:]
        CrashVault.appVersion = info["CFBundleShortVersionString"] as? String ?? ""
        CrashVault.build = info["CFBundleVersion"] as? String ?? ""
        CrashVault.device = "Apple \(machine())"
        CrashVault.sdk = Int(UIDevice.current.systemVersion.split(separator: ".").first ?? "") ?? 0
        NSSetUncaughtExceptionHandler { e in
            CrashHandlers.vault?.record(kind: "crash", summary: "\(e.name.rawValue): \(e.reason ?? "")",
                                        trace: e.callStackSymbols.joined(separator: "\n"), thread: Thread.current.name ?? (Thread.isMainThread ? "main" : nil))
        }
        for s in signals { signal(s, CrashHandlers.onSignal) }
    }

    /// Best effort inside a signal handler (as every crash reporter does): the report is written, then the default action runs.
    private static let onSignal: @convention(c) (Int32) -> Void = { sig in
        let name = CrashHandlers.signalName(sig)
        CrashHandlers.vault?.record(kind: "crash", summary: "Signal \(name)", trace: Thread.callStackSymbols.joined(separator: "\n"),
                                    thread: Thread.isMainThread ? "main" : nil)
        signal(sig, SIG_DFL)
        raise(sig)
    }

    private static func signalName(_ s: Int32) -> String {
        switch s {
        case SIGABRT: return "SIGABRT"
        case SIGSEGV: return "SIGSEGV"
        case SIGBUS: return "SIGBUS"
        case SIGILL: return "SIGILL"
        case SIGFPE: return "SIGFPE"
        case SIGTRAP: return "SIGTRAP"
        default: return "\(s)"
        }
    }

    private static func machine() -> String {
        var sys = utsname()
        uname(&sys)
        let mirror = Mirror(reflecting: sys.machine)
        let chars = mirror.children.compactMap { $0.value as? Int8 }.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }
        let id = String(decoding: chars, as: UTF8.self)
        return id.isEmpty ? UIDevice.current.model : id
    }
}
