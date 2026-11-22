import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

struct SettingsView: View {
    @Environment(AppState.self) private var app
    @State private var displayName = ""
    @State private var bio = ""
    @State private var isPrivate = false
    @State private var units = "original"
    @State private var voice = UserDefaults.standard.string(forKey: "voiceIdentifier") ?? ""
    @State private var exporting = false
    @State private var shareItems: ShareItems?
    @State private var showRestore = false
    @State private var message: String?
    @State private var loaded = false
    @State private var reader = SpeechReader()

    private var voices: [AVSpeechSynthesisVoice] {
        let lang = Locale.current.language.languageCode?.identifier ?? "en"
        return AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix(lang) }
            .sorted { ($0.quality.rawValue, $0.name) > ($1.quality.rawValue, $1.name) }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Display name", text: $displayName).onSubmit { save(["display_name": AnyEncodable(displayName)]) }
                    TextField("Bio", text: $bio, axis: .vertical).onSubmit { save(["bio": AnyEncodable(bio)]) }
                    Toggle("Private account", isOn: $isPrivate)
                        .onChange(of: isPrivate) { _, v in if loaded { save(["is_private": AnyEncodable(v)]) } }
                } header: {
                    Text("Profile")
                } footer: {
                    Text("Private accounts hide your profile, recipes and journal from everyone else on the server. Share links you send still work.")
                }

                Section {
                    Picker("Measurements", selection: $units) {
                        Text("As written").tag("original")
                        Text("Metric (g, ml, °C)").tag("metric")
                        Text("US (cups, oz, °F)").tag("imperial")
                    }
                    .onChange(of: units) { _, v in if loaded { save(["units": AnyEncodable(v)]) } }
                    Picker("Read-aloud voice", selection: $voice) {
                        Text("Best available").tag("")
                        ForEach(voices, id: \.identifier) { v in
                            Text("\(v.name)\(v.quality == .premium ? " (Premium)" : v.quality == .enhanced ? " (Enhanced)" : "")")
                                .tag(v.identifier)
                        }
                    }
                    .onChange(of: voice) { _, v in
                        UserDefaults.standard.set(v.isEmpty ? nil : v, forKey: "voiceIdentifier")
                        reader.speak("Preheat the oven to two hundred degrees.")
                    }
                } header: {
                    Text("Cooking")
                } footer: {
                    Text("For natural AI voices, download Premium or Enhanced voices in iOS Settings → Accessibility → Spoken Content → Voices.")
                }

                Section {
                    Button {
                        Task { await export() }
                    } label: {
                        HStack {
                            Label("Export all recipes", systemImage: "square.and.arrow.up")
                            if exporting {
                                Spacer()
                                ProgressView()
                            }
                        }
                    }
                    Button { showRestore = true } label: { Label("Restore from export", systemImage: "square.and.arrow.down") }
                    if let message { Text(message).font(.footnote).foregroundStyle(.secondary) }
                } header: {
                    Text("Your data")
                } footer: {
                    Text("Exports a zip with every recipe as Markdown plus a JSON backup you can restore on any Mise server.")
                }

                Section("Server") {
                    LabeledContent("Address", value: SharedConfig.serverURL?.absoluteString ?? "—")
                    LabeledContent("Version", value: app.server?.version ?? "—")
                    LabeledContent("AI features", value: app.aiEnabled ? "On" : "Off")
                    LabeledContent("Video speech-to-text", value: (app.server?.transcription ?? false) ? "On" : "Off")
                    if let s = SharedConfig.serverURL, let u = URL(string: s.absoluteString + "/") {
                        Link("Open web reader", destination: u)
                    }
                }

                Section {
                    LabeledContent("Signed in as", value: "@\(app.user?.username ?? "")")
                    Button("Sign out", role: .destructive) { app.signOut() }
                }
            }
            .navigationTitle("Settings")
            .onAppear {
                guard let u = app.user else { return }
                displayName = u.displayName
                bio = u.bio ?? ""
                isPrivate = u.isPrivate
                units = u.units ?? "original"
                DispatchQueue.main.async { loaded = true }
            }
            .sheet(item: $shareItems) { ActivityView(items: $0.items) }
            .fileImporter(isPresented: $showRestore, allowedContentTypes: [.json]) { result in
                guard case .success(let url) = result else { return }
                Task { await restore(url) }
            }
        }
    }

    private func save(_ fields: [String: AnyEncodable]) {
        Task {
            if let u = try? await API.shared.updateMe(fields) {
                app.user = u
                app.libraryVersion += 1
            }
        }
    }

    private func export() async {
        exporting = true
        defer { exporting = false }
        do {
            let data = try await API.shared.download("/api/export.zip")
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("mise-export.zip")
            try data.write(to: url)
            shareItems = ShareItems(items: [url])
        } catch {
            message = error.localizedDescription
        }
    }

    private func restore(_ url: URL) async {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            let res = try await API.shared.importBackup(data)
            message = "Restored \(res.imported) recipes."
            app.libraryVersion += 1
        } catch {
            message = error.localizedDescription
        }
    }
}
