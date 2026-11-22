import SwiftUI

struct LibraryView: View {
    enum Mode: String, CaseIterable, Identifiable {
        case all = "All", favorites = "Favorites", categories = "Categories", collections = "Collections"
        var id: String { rawValue }
    }

    @Environment(AppState.self) private var app
    @State private var path = NavigationPath()
    @State private var mode: Mode = .all
    @State private var search = ""
    @State private var sort = "recent"
    @State private var recipes: [RecipeSummary] = []
    @State private var categories: [CategoryCount] = []
    @State private var collections: [RecipeCollection] = []
    @State private var loading = false
    @State private var error: String?
    @State private var showImport = false
    @State private var newCollection = ""
    @State private var showNewCollection = false
    @State private var sharedRecipe: RecipeDetail?

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                Picker("View", selection: $mode) {
                    ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)

                if let error {
                    Text(error).foregroundStyle(.red).font(.footnote).padding()
                }

                switch mode {
                case .all, .favorites:
                    if recipes.isEmpty && !loading {
                        emptyState
                    } else {
                        RecipeGrid(recipes: recipes, onChange: { Task { await load() } })
                    }
                case .categories:
                    CategoryGrid(items: categories.map { ($0.name, $0.count, $0.imageUrl) }) { name in
                        path.append(RecipeFilter(title: name, category: name, collectionId: nil))
                    }
                case .collections:
                    collectionsList
                }
            }
            .navigationTitle("Recipes")
            .searchable(text: $search, prompt: "Search recipes or ingredients")
            .refreshable { await load() }
            .task(id: "\(mode.rawValue)|\(search)|\(sort)|\(app.libraryVersion)") {
                try? await Task.sleep(for: .milliseconds(search.isEmpty ? 0 : 250))
                await load()
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Picker("Sort", selection: $sort) {
                            Text("Recently added").tag("recent")
                            Text("Title").tag("title")
                            Text("Recently cooked").tag("cooked")
                            Text("Rating").tag("rating")
                            Text("Quickest").tag("time")
                        }
                    } label: { Image(systemName: "arrow.up.arrow.down") }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showImport = true } label: { Image(systemName: "plus.circle.fill").font(.title3) }
                        .accessibilityLabel("Add recipe")
                }
            }
            .navigationDestination(for: RecipeRef.self) { RecipeDetailView(recipeId: $0.id) }
            .navigationDestination(for: RecipeFilter.self) { FilteredRecipesView(filter: $0) }
            .sheet(isPresented: $showImport) { ImportView(initialURL: nil) }
            .sheet(item: Binding(get: { app.pendingImportURL.map { IdentifiedString(value: $0) } },
                                 set: { app.pendingImportURL = $0?.value })) { ImportView(initialURL: $0.value) }
            .sheet(item: $sharedRecipe) { r in
                NavigationStack { RecipeDetailView(recipeId: r.id, preloaded: r, shareToken: app.pendingShareToken) }
                    .onDisappear { app.pendingShareToken = nil }
            }
            .onChange(of: app.openRecipeId, initial: true) { _, id in
                guard let id else { return }
                path = NavigationPath()
                path.append(RecipeRef(id: id))
                app.openRecipeId = nil
            }
            .onChange(of: app.pendingShareToken, initial: true) { _, token in
                guard let token else { return }
                Task { sharedRecipe = try? await API.shared.sharedRecipe(token: token) }
            }
            .alert("New collection", isPresented: $showNewCollection) {
                TextField("Name", text: $newCollection)
                Button("Create") {
                    let name = newCollection
                    newCollection = ""
                    Task { _ = try? await API.shared.createCollection(name); await load() }
                }
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(search.isEmpty ? "No recipes yet" : "No matches", systemImage: "book.closed")
        } description: {
            Text(search.isEmpty ? "Save recipes from websites, YouTube, TikTok, Instagram, photos or documents. Tip: use the Share button in Safari or TikTok and pick “Save to Mise”."
                                : "Try another word.")
        } actions: {
            if search.isEmpty { Button("Add a recipe") { showImport = true }.buttonStyle(.borderedProminent) }
        }
        .padding(.top, 40)
    }

    private var collectionsList: some View {
        VStack(alignment: .leading) {
            Button { showNewCollection = true } label: { Label("New collection", systemImage: "folder.badge.plus") }
                .padding(.horizontal)
            CategoryGrid(items: collections.map { ($0.name, $0.count, $0.imageUrl) }) { name in
                if let c = collections.first(where: { $0.name == name }) {
                    path.append(RecipeFilter(title: c.name, category: nil, collectionId: c.id))
                }
            } menu: { name in
                if let c = collections.first(where: { $0.name == name }) {
                    Button(role: .destructive) {
                        Task { try? await API.shared.deleteCollection(c.id); await load() }
                    } label: { Label("Delete collection", systemImage: "trash") }
                }
            }
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            switch mode {
            case .all: recipes = try await API.shared.recipes(query: search, sort: sort)
            case .favorites: recipes = try await API.shared.recipes(query: search, favorite: true, sort: sort)
            case .categories: categories = try await API.shared.categories()
            case .collections: collections = try await API.shared.collections()
            }
            error = nil
        } catch is CancellationError {
        } catch {
            if (error as? URLError)?.code != .cancelled { self.error = error.localizedDescription }
        }
    }
}

struct IdentifiedString: Identifiable { let value: String; var id: String { value } }

struct RecipeFilter: Hashable {
    let title: String
    let category: String?
    let collectionId: Int?
}

struct FilteredRecipesView: View {
    let filter: RecipeFilter
    @Environment(AppState.self) private var app
    @State private var recipes: [RecipeSummary] = []

    var body: some View {
        ScrollView { RecipeGrid(recipes: recipes, onChange: { Task { await load() } }) }
            .navigationTitle(filter.title)
            .task(id: app.libraryVersion) { await load() }
            .refreshable { await load() }
    }

    private func load() async {
        recipes = (try? await API.shared.recipes(category: filter.category, collectionId: filter.collectionId)) ?? recipes
    }
}

struct RecipeGrid: View {
    let recipes: [RecipeSummary]
    var onChange: () -> Void = {}
    @Environment(AppState.self) private var app
    @State private var collectionTarget: RecipeSummary?

    private let columns = [GridItem(.adaptive(minimum: 160), spacing: 14)]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 18) {
            ForEach(recipes) { r in
                NavigationLink(value: RecipeRef(id: r.id)) { RecipeCard(recipe: r) }
                    .buttonStyle(.plain)
                    .contextMenu {
                        Button {
                            Task { _ = try? await API.shared.patchRecipe(r.id, ["favorite": AnyEncodable(!r.favorite)]); onChange() }
                        } label: { Label(r.favorite ? "Remove favorite" : "Favorite", systemImage: r.favorite ? "heart.slash" : "heart") }
                        Button { collectionTarget = r } label: { Label("Add to collection", systemImage: "folder") }
                        Button(role: .destructive) {
                            Task { try? await API.shared.deleteRecipe(r.id); app.libraryVersion += 1 }
                        } label: { Label("Delete", systemImage: "trash") }
                    }
            }
        }
        .padding()
        .sheet(item: $collectionTarget) { r in CollectionPickerView(recipeId: r.id, selected: []) }
    }
}

struct RecipeCard: View {
    let recipe: RecipeSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            RemoteImage(url: recipe.imageUrl)
                .aspectRatio(4 / 3, contentMode: .fill)
                .frame(minWidth: 0, maxWidth: .infinity)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(alignment: .topTrailing) {
                    if recipe.favorite {
                        Image(systemName: "heart.fill").foregroundStyle(.white).padding(7)
                            .background(.black.opacity(0.35), in: Circle()).padding(6)
                    }
                }
            Text(recipe.title).font(.subheadline.weight(.semibold)).lineLimit(2).multilineTextAlignment(.leading)
            HStack(spacing: 6) {
                if let t = formatMinutes(recipe.totalTime) { Label(t, systemImage: "clock") }
                if let d = recipe.sourceDomain { Text(d).lineLimit(1) }
            }
            .font(.caption).foregroundStyle(.secondary).labelStyle(.titleAndIcon)
        }
    }
}

struct RemoteImage: View {
    let url: String?

    var body: some View {
        Color(.secondarySystemBackground)
            .overlay {
                if let s = url, let u = URL(string: s) {
                    AsyncImage(url: u, transaction: Transaction(animation: .easeOut(duration: 0.2))) { phase in
                        switch phase {
                        case .success(let img): img.resizable().scaledToFill()
                        case .failure: placeholder
                        default: ProgressView()
                        }
                    }
                } else {
                    placeholder
                }
            }
            .clipped()
    }

    private var placeholder: some View {
        Image(systemName: "fork.knife").font(.title).foregroundStyle(.tertiary)
    }
}

struct CategoryGrid<MenuContent: View>: View {
    let items: [(String, Int, String?)]
    let onTap: (String) -> Void
    let menu: (String) -> MenuContent

    init(items: [(String, Int, String?)], onTap: @escaping (String) -> Void,
         @ViewBuilder menu: @escaping (String) -> MenuContent) {
        self.items = items
        self.onTap = onTap
        self.menu = menu
    }

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: 14)], spacing: 14) {
            ForEach(items, id: \.0) { item in
                Button { onTap(item.0) } label: {
                    ZStack(alignment: .bottomLeading) {
                        RemoteImage(url: item.2).aspectRatio(3 / 2, contentMode: .fill)
                        LinearGradient(colors: [.clear, .black.opacity(0.65)], startPoint: .center, endPoint: .bottom)
                        VStack(alignment: .leading, spacing: 0) {
                            Text(item.0).font(.headline).foregroundStyle(.white).lineLimit(2)
                            Text("\(item.1) recipe\(item.1 == 1 ? "" : "s")").font(.caption).foregroundStyle(.white.opacity(0.85))
                        }
                        .padding(10)
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(.plain)
                .contextMenu { menu(item.0) }
            }
        }
        .padding()
    }
}

extension CategoryGrid where MenuContent == EmptyView {
    init(items: [(String, Int, String?)], onTap: @escaping (String) -> Void) {
        self.init(items: items, onTap: onTap, menu: { _ in EmptyView() })
    }
}
