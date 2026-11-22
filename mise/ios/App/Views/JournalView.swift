import PhotosUI
import SwiftUI

struct JournalView: View {
    @Environment(AppState.self) private var app
    @State private var entries: [JournalEntry] = []
    @State private var showNew = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if let error { Text(error).foregroundStyle(.red) }
                if entries.isEmpty {
                    ContentUnavailableView("Nothing cooked yet", systemImage: "fork.knife",
                                           description: Text("Log what you cook — with a photo, rating and notes — from any recipe's ••• menu or the + button."))
                }
                ForEach(entries) { e in
                    JournalRow(entry: e)
                        .swipeActions {
                            Button(role: .destructive) {
                                Task { try? await API.shared.deleteJournal(e.id); await load() }
                            } label: { Label("Delete", systemImage: "trash") }
                        }
                }
            }
            .listStyle(.plain)
            .navigationTitle("Journal")
            .navigationDestination(for: RecipeRef.self) { RecipeDetailView(recipeId: $0.id) }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNew = true } label: { Image(systemName: "plus.circle.fill").font(.title3) }
                }
            }
            .sheet(isPresented: $showNew, onDismiss: { Task { await load() } }) { LogCookView(recipe: nil) }
            .task(id: app.libraryVersion) { await load() }
            .refreshable { await load() }
        }
    }

    private func load() async {
        do { entries = try await API.shared.journal(); error = nil } catch is CancellationError {} catch {
            self.error = error.localizedDescription
        }
    }
}

struct JournalRow: View {
    let entry: JournalEntry
    var showUser = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                if showUser, let u = entry.user {
                    NavigationLink(value: UserRef(username: u.username)) {
                        Text(u.displayName).font(.subheadline.weight(.semibold))
                    }
                    .buttonStyle(.plain)
                    Text("cooked").font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                if let d = Date.fromISO(entry.cookedAt) {
                    Text(d, format: .relative(presentation: .named)).font(.caption).foregroundStyle(.secondary)
                }
            }
            if let r = entry.recipe {
                NavigationLink(value: RecipeRef(id: r.id)) {
                    Text(r.title).font(.headline)
                }
                .buttonStyle(.plain)
            }
            if let p = entry.photoUrl {
                RemoteImage(url: p).frame(height: 220).frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            if let rating = entry.rating, rating > 0 { Stars(value: rating) }
            if let t = entry.text, !t.isEmpty { Text(t) }
        }
        .padding(.vertical, 6)
    }
}

struct UserRef: Hashable { let username: String }

struct Stars: View {
    let value: Int
    var body: some View {
        HStack(spacing: 2) {
            ForEach(1...5, id: \.self) { i in
                Image(systemName: i <= value ? "star.fill" : "star").foregroundStyle(.orange).font(.caption)
            }
        }
    }
}

struct LogCookView: View {
    let recipe: RecipeDetail?
    @Environment(\.dismiss) private var dismiss
    @Environment(AppState.self) private var app
    @State private var text = ""
    @State private var rating = 0
    @State private var isPublic = true
    @State private var photo: PhotosPickerItem?
    @State private var photoData: Data?
    @State private var recipes: [RecipeSummary] = []
    @State private var recipeId: Int?
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                if let recipe {
                    Section { Text(recipe.title).font(.headline) }
                } else {
                    Section("Recipe") {
                        Picker("Recipe", selection: $recipeId) {
                            Text("None").tag(Int?.none)
                            ForEach(recipes) { Text($0.title).tag(Int?.some($0.id)) }
                        }
                    }
                }
                Section("How was it?") {
                    HStack {
                        ForEach(1...5, id: \.self) { i in
                            Image(systemName: i <= rating ? "star.fill" : "star")
                                .font(.title2).foregroundStyle(.orange)
                                .onTapGesture { rating = (rating == i ? 0 : i) }
                        }
                    }
                    TextField("Notes — what you changed, what to try next time", text: $text, axis: .vertical)
                        .lineLimit(3...8)
                }
                Section {
                    PhotosPicker(selection: $photo, matching: .images) {
                        if let photoData, let img = UIImage(data: photoData) {
                            Image(uiImage: img).resizable().scaledToFill().frame(height: 180).clipped()
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                        } else {
                            Label("Add a photo", systemImage: "camera")
                        }
                    }
                    Toggle("Share with friends", isOn: $isPublic)
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }
            .navigationTitle("I cooked this")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else { Button("Save") { Task { await save() } } }
                }
            }
            .task {
                isPublic = !(app.user?.isPrivate ?? false)
                if recipe == nil { recipes = (try? await API.shared.recipes(sort: "title")) ?? [] }
            }
            .onChange(of: photo) { _, item in
                Task {
                    if let item, let data = try? await item.loadTransferable(type: Data.self),
                       let img = UIImage(data: data) {
                        photoData = img.resizedJPEG(maxSide: 1600)
                    }
                }
            }
        }
    }

    private func save() async {
        busy = true
        defer { busy = false }
        do {
            var url: String?
            if let photoData { url = try await API.shared.uploadMedia(jpeg: photoData) }
            _ = try await API.shared.addJournal(recipeId: recipe?.id ?? recipeId, text: text,
                                                rating: rating, photoUrl: url, isPublic: isPublic)
            app.libraryVersion += 1
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
