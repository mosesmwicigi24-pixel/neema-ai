import Foundation

/// The dashboard's polls (Android `DashboardViewModel.poll`): fetch, then wait
/// out the interval — unless the app leaves and comes back meanwhile, which
/// refetches at once; while it sits in the background the loop waits for it
/// to return rather than fetching into the void.
public enum Polling {
    public static func loop(every ms: Int64, foreground: Watched<Bool>, sleep: @escaping Sleeper,
                            fetch: @escaping @Sendable () async -> Void) -> Task<Void, Never> {
        Task {
            while !Task.isCancelled {
                await fetch()
                let returned = await leftAndCameBack(foreground, within: ms, sleep: sleep)
                if Task.isCancelled { return }
                if !returned && !foreground.value { await await_(foreground, equals: true) }
            }
        }
    }

    /// `withTimeoutOrNull(ms) { fg.first { !it }; fg.first { it } }`: true when the
    /// app left and came back before `ms` passed.
    public static func leftAndCameBack(_ fg: Watched<Bool>, within ms: Int64, sleep: @escaping Sleeper) async -> Bool {
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { _ = try? await sleep(ms); return false }
            group.addTask {
                await await_(fg, equals: false)
                if Task.isCancelled { return false }
                await await_(fg, equals: true)
                return !Task.isCancelled
            }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
    }
}
