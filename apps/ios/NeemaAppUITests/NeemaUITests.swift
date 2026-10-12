import XCTest

/// The flows a person drives, on the simulator against the recorded backend
/// (`-neema-canned`: `CannedBackend` in the app). Every test launches the app
/// signed out; the canned sign-in takes any email with the password `neema`.
/// Elements are found by the accessibility labels the screens already carry
/// for VoiceOver, and the sign-in form by its identifiers.
final class NeemaUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-neema-canned"]
        app.launch()
    }

    override func tearDown() {
        app.terminate()
        app = nil
    }

    // MARK: Helpers

    /// A bottom tab or sidebar row by its label: "Inbox" also matches "Inbox, 2 new".
    private func nav(_ label: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", label, label + ",")).firstMatch
    }

    /// Any element whose label carries the text (a row may fold its texts into one element).
    private func text(_ s: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", s)).firstMatch
    }

    private func signIn(password: String = "neema", file: StaticString = #filePath, line: UInt = #line) {
        let email = app.textFields["login.email"]
        XCTAssertTrue(email.waitForExistence(timeout: 15), "the sign-in form did not appear", file: file, line: line)
        email.tap()
        email.typeText("moses@bethanyhouse.co.ke")
        let pw = app.secureTextFields["login.password"]
        pw.tap()
        pw.typeText(password)
        app.buttons["login.submit"].tap()
    }

    private func signedIn(file: StaticString = #filePath, line: UInt = #line) {
        let shown = nav("Inbox").waitForExistence(timeout: 20)
        // What was on screen instead, in the build log (the hierarchy as VoiceOver sees it).
        if !shown { print("neema-ui: no shell after sign-in; hierarchy:\n\(app.debugDescription)") }
        XCTAssertTrue(shown, "the shell did not appear after sign-in", file: file, line: line)
    }

    // MARK: Sign-in

    func testSignInOpensTheInbox() {
        signIn()
        signedIn()
        XCTAssertTrue(nav("Inbox").isSelected)
        // The first thread of the fixtures is on the list.
        XCTAssertTrue(text("Fr. Peter Kamau").waitForExistence(timeout: 15))
        XCTAssertFalse(app.textFields["login.email"].exists)
    }

    func testWrongPasswordKeepsTheFormAndSaysSo() {
        signIn(password: "not-it")
        XCTAssertTrue(text("Invalid email or password").waitForExistence(timeout: 15))
        XCTAssertTrue(app.textFields["login.email"].exists)
        XCTAssertFalse(nav("Inbox").exists)
    }

    // MARK: Navigation

    func testBottomTabsSwitchScreens() {
        signIn()
        signedIn()
        for label in ["Calls", "Orders", "Inbox"] {
            let tab = nav(label)
            XCTAssertTrue(tab.waitForExistence(timeout: 10), label)
            tab.tap()
            XCTAssertTrue(tab.waitForExistence(timeout: 5))
            XCTAssertTrue(tab.isSelected, "\(label) did not become the current tab")
        }
    }

    func testMoreOpensTheDrawerToSettings() {
        signIn()
        signedIn()
        let more = nav("More")
        if more.waitForExistence(timeout: 5) {
            // A phone: the fifth tab opens the drawer with the rest of the navigation.
            more.tap()
            let settings = nav("Settings")
            XCTAssertTrue(settings.waitForExistence(timeout: 10))
            settings.tap()
            XCTAssertTrue(more.waitForExistence(timeout: 5))
            XCTAssertTrue(more.isSelected, "More is lit while a drawer screen is current")
        } else {
            // A wide window: the sidebar is docked.
            let settings = nav("Settings")
            XCTAssertTrue(settings.waitForExistence(timeout: 10))
            settings.tap()
            XCTAssertTrue(settings.isSelected)
        }
    }

    func testOrdersShowsTheFixturesOrder() {
        signIn()
        signedIn()
        nav("Orders").tap()
        XCTAssertTrue(text("BH-1042").waitForExistence(timeout: 15))
    }

    // MARK: The thread

    func testOpeningAThreadShowsIt() {
        signIn()
        signedIn()
        let row = text("Fr. Peter Kamau")
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        row.tap()
        // The full-screen thread on a phone: the header's actions and the messages.
        XCTAssertTrue(app.buttons["Call on WhatsApp"].waitForExistence(timeout: 15))
        XCTAssertTrue(text("Can you deliver to Nyeri by Friday?").waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Back"].exists)
    }

    // MARK: Sign-out

    func testSignOutReturnsToTheForm() {
        signIn()
        signedIn()
        let more = nav("More")
        if more.waitForExistence(timeout: 5) { more.tap() }
        let account = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Account:'")).firstMatch
        XCTAssertTrue(account.waitForExistence(timeout: 10))
        account.tap()
        let signOut = app.buttons["Sign out"]
        XCTAssertTrue(signOut.waitForExistence(timeout: 10))
        signOut.tap()
        XCTAssertTrue(app.textFields["login.email"].waitForExistence(timeout: 15))
    }
}
