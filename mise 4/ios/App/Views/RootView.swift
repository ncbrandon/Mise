import SwiftUI

struct RootView: View {
    @Environment(AppState.self) private var app

    var body: some View {
        @Bindable var app = app
        Group {
            if app.booting {
                ProgressView()
            } else if app.user == nil {
                LoginView()
            } else {
                TabView(selection: $app.tab) {
                    LibraryView()
                        .tabItem { Label("Recipes", systemImage: "book.closed") }
                        .tag(AppTab.library)
                    ShoppingListView()
                        .tabItem { Label("Shopping", systemImage: "cart") }
                        .tag(AppTab.shopping)
                    JournalView()
                        .tabItem { Label("Journal", systemImage: "fork.knife") }
                        .tag(AppTab.journal)
                    FriendsView()
                        .tabItem { Label("Friends", systemImage: "person.2") }
                        .tag(AppTab.friends)
                    SettingsView()
                        .tabItem { Label("Settings", systemImage: "gearshape") }
                        .tag(AppTab.settings)
                }
            }
        }
    }
}

struct LoginView: View {
    @Environment(AppState.self) private var app
    @State private var server = SharedConfig.serverURL?.absoluteString ?? ""
    @State private var username = ""
    @State private var password = ""
    @State private var displayName = ""
    @State private var registering = false
    @State private var info: ServerInfo?
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Mise").font(.system(.largeTitle, design: .serif).bold())
                        Text("Clean recipes from any website, video, photo or document — on your own server.")
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 6)
                    .listRowBackground(Color.clear)
                }
                Section {
                    TextField("http://192.168.1.50:8000", text: $server)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onSubmit { Task { await check() } }
                    if let info {
                        Label("Connected to \(info.name) \(info.version)\(info.ai ? " · AI on" : "")",
                              systemImage: "checkmark.circle.fill").foregroundStyle(.green).font(.footnote)
                    }
                } header: { Text("Server") } footer: {
                    Text("The address of the Mise server running in your Portainer stack.")
                }
                Section(registering ? "Create account" : "Sign in") {
                    TextField("Username or email", text: $username)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Password", text: $password)
                        .textContentType(registering ? .newPassword : .password)
                    if registering {
                        TextField("Display name (optional)", text: $displayName)
                    }
                }
                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                }
                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Spacer()
                            if busy {
                                ProgressView()
                            } else {
                                Text(registering ? "Create account" : "Sign in").bold()
                            }
                            Spacer()
                        }
                    }
                    .disabled(busy || server.isEmpty || username.isEmpty || password.count < (registering ? 6 : 1))
                    Button(registering ? "I already have an account" : "Create an account") { registering.toggle() }
                        .frame(maxWidth: .infinity)
                }
            }
        }
    }

    private func check() async {
        guard let url = SharedConfig.normalizeServer(server) else { return }
        do {
            info = try await API.shared.serverInfo(at: url)
            error = nil
        } catch {
            info = nil
            self.error = error.localizedDescription
        }
    }

    private func submit() async {
        guard let url = SharedConfig.normalizeServer(server) else { error = "Enter your server address"; return }
        busy = true
        defer { busy = false }
        do {
            let info = try await API.shared.serverInfo(at: url)
            SharedConfig.serverURL = url
            let auth = registering
                ? try await API.shared.register(username: username, password: password, displayName: displayName.isEmpty ? nil : displayName)
                : try await API.shared.login(username: username, password: password)
            app.signedIn(auth, server: info)
        } catch {
            self.error = error.localizedDescription
        }
    }
}
