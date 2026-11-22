import SwiftUI

@main
struct MiseApp: App {
    @State private var app = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .tint(Color.accentColor)
                .onOpenURL { app.handle(url: $0) }
                .task { await app.bootstrap() }
        }
    }
}

enum AppTab: Hashable { case library, shopping, journal, friends, settings }

struct RecipeRef: Hashable { let id: Int }

@MainActor
@Observable
final class AppState {
    var user: User?
    var server: ServerInfo?
    var booting = true
    var tab: AppTab = .library

    /// Set by deep links (mise://import?url=...) or the clipboard; shows the import sheet.
    var pendingImportURL: String?
    /// mise://recipe?share=<token>
    var pendingShareToken: String?
    /// Bumped whenever recipes change so lists reload.
    var libraryVersion = 0
    /// After an import the library pushes this recipe.
    var openRecipeId: Int?

    var units: String { user?.units ?? "original" }
    var aiEnabled: Bool { server?.ai ?? false }

    init() {
        NotificationCenter.default.addObserver(forName: .miseUnauthorized, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.signOut() }
        }
    }

    func bootstrap() async {
        defer { booting = false }
        guard SharedConfig.serverURL != nil, SharedConfig.token != nil else { return }
        server = try? await API.shared.serverInfo()
        do {
            user = try await API.shared.me()
        } catch let e as APIError where e.status == 401 {
            signOut()
        } catch {
            // offline: keep the token, show the error inside screens
        }
    }

    func signedIn(_ auth: AuthResponse, server: ServerInfo?) {
        SharedConfig.token = auth.token
        user = auth.user
        self.server = server
        libraryVersion += 1
    }

    func signOut() {
        SharedConfig.token = nil
        user = nil
    }

    func handle(url: URL) {
        guard url.scheme == "mise", let comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return }
        let q = Dictionary((comps.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { first, _ in first })
        switch url.host {
        case "import":
            if let u = q["url"], !u.isEmpty { tab = .library; pendingImportURL = u }
        case "recipe":
            if let t = q["share"], !t.isEmpty { tab = .library; pendingShareToken = t }
            if let id = q["id"].flatMap(Int.init) { tab = .library; openRecipeId = id }
        default:
            break
        }
    }

    func didImport(_ recipe: RecipeDetail) {
        libraryVersion += 1
        tab = .library
        openRecipeId = recipe.id
    }
}
