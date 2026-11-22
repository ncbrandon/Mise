import SwiftUI

struct RecipeDetailView: View {
    let recipeId: Int
    var preloaded: RecipeDetail? = nil
    var shareToken: String? = nil

    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var recipe: RecipeDetail?
    @State private var servings: Double?
    @State private var scale: Double?
    @State private var units: String?
    @State private var checked: Set<Int> = []
    @State private var error: String?
    @State private var busy: String?
    @State private var showCook = false
    @State private var showEdit = false
    @State private var showLog = false
    @State private var showCollections = false
    @State private var showShopping = false
    @State private var showNotes = false
    @State private var confirmDelete = false
    @State private var shareItems: ShareItems?
    @State private var reader = SpeechReader()

    var body: some View {
        Group {
            if let r = recipe {
                content(r)
            } else if let error {
                ContentUnavailableView("Couldn't load recipe", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView()
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: "\(servings ?? -1)|\(scale ?? -1)|\(units ?? "-")") { await load() }
    }

    // MARK: - Content

    @ViewBuilder
    private func content(_ r: RecipeDetail) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if r.imageUrl != nil {
                    RemoteImage(url: r.imageUrl)
                        .frame(height: 260)
                        .frame(maxWidth: .infinity)
                }
                VStack(alignment: .leading, spacing: 14) {
                    header(r)
                    if !r.isOwner { saveBanner(r) }
                    controls(r)
                    ingredientsSection(r)
                    stepsSection(r)
                    if r.isOwner { extrasSection(r) }
                    if r.isOwner, let notes = r.notes, !notes.isEmpty {
                        sectionTitle("My notes")
                        Text(notes).padding(12).frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.yellow.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
                    }
                    if let src = r.sourceUrl, let u = URL(string: src) {
                        Link(destination: u) { Label("Original recipe", systemImage: "safari") }
                            .font(.footnote).padding(.top, 8)
                    }
                }
                .padding()
            }
        }
        .safeAreaInset(edge: .bottom) {
            Button { showCook = true } label: {
                Label("Start cooking", systemImage: "flame").frame(maxWidth: .infinity).padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .padding(.horizontal).padding(.bottom, 6)
        }
        .toolbar { toolbar(r) }
        .fullScreenCover(isPresented: $showCook) { CookModeView(recipe: r) }
        .sheet(isPresented: $showEdit) {
            RecipeEditView(existing: r) { updated in recipe = updated; app.libraryVersion += 1 }
        }
        .sheet(isPresented: $showLog) { LogCookView(recipe: r) }
        .sheet(isPresented: $showCollections) { CollectionPickerView(recipeId: r.id, selected: Set(r.collectionIds)) { Task { await load() } } }
        .sheet(isPresented: $showShopping) { AddToShoppingView(recipe: r) }
        .sheet(isPresented: $showNotes) {
            NotesEditor(text: r.notes ?? "") { text in
                Task { if let u = try? await API.shared.patchRecipe(r.id, ["notes": AnyEncodable(text)]) { recipe = u } }
            }
        }
        .sheet(item: $shareItems) { ActivityView(items: $0.items) }
        .confirmationDialog("Delete this recipe?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                Task {
                    try? await API.shared.deleteRecipe(r.id)
                    app.libraryVersion += 1
                    dismiss()
                }
            }
        }
    }

    private func header(_ r: RecipeDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(r.title).font(.system(.title, design: .serif).bold())
            if let d = r.description, !d.isEmpty {
                Text(d).foregroundStyle(.secondary)
            }
            HStack(spacing: 14) {
                if let t = formatMinutes(r.prepTime) { meta("Prep", t) }
                if let t = formatMinutes(r.cookTime) { meta("Cook", t) }
                if let t = formatMinutes(r.totalTime) { meta("Total", t) }
            }
            if !r.categories.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        ForEach(r.categories, id: \.self) { c in
                            Text(c).font(.caption).padding(.horizontal, 10).padding(.vertical, 5)
                                .background(Color.accentColor.opacity(0.12), in: Capsule())
                        }
                    }
                }
            }
            if let author = r.author { Text("By \(author)").font(.footnote).foregroundStyle(.secondary) }
        }
    }

    private func meta(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label.uppercased()).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.subheadline.weight(.semibold))
        }
    }

    private func saveBanner(_ r: RecipeDetail) -> some View {
        HStack {
            Text("Shared by \(r.owner ?? "a friend")").font(.subheadline)
            Spacer()
            Button("Save to my recipes") {
                Task {
                    do {
                        let mine = try await API.shared.copyRecipe(r.id, share: shareToken)
                        app.didImport(mine)
                        dismiss()
                    } catch { self.error = error.localizedDescription }
                }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(12)
        .background(Color.accentColor.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
    }

    private func controls(_ r: RecipeDetail) -> some View {
        HStack {
            if let base = r.servings, base > 0 {
                let cur = r.currentServings ?? base
                Stepper(onIncrement: { servings = cur + 1 },
                        onDecrement: { if cur > 1 { servings = cur - 1 } else if cur > 0.5 { servings = 0.5 } }) {
                    Text("\(formatNumber(cur)) \(cur == 1 ? "serving" : "servings")").font(.subheadline.weight(.medium))
                }
            } else {
                Menu {
                    ForEach([0.5, 1, 2, 3, 4], id: \.self) { s in
                        Button("\(formatNumber(s))×") { scale = s }
                    }
                } label: {
                    Label("\(formatNumber(r.scale))× recipe", systemImage: "arrow.up.left.and.arrow.down.right")
                        .font(.subheadline)
                }
            }
            Spacer()
            Picker("Units", selection: Binding(get: { r.units }, set: { units = $0 })) {
                Text("Original").tag("original")
                Text("Metric").tag("metric")
                Text("US").tag("imperial")
            }
            .pickerStyle(.menu)
        }
        .padding(10)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s).font(.system(.title3, design: .serif).bold()).padding(.top, 10)
    }

    private func ingredientsSection(_ r: RecipeDetail) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            sectionTitle("Ingredients").padding(.bottom, 6)
            ForEach(Array(r.ingredients.enumerated()), id: \.offset) { idx, ing in
                if ing.group != nil && (idx == 0 || r.ingredients[idx - 1].group != ing.group) {
                    Text(ing.group!.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        .padding(.top, 14).padding(.bottom, 4)
                }
                Button {
                    if checked.contains(idx) { checked.remove(idx) } else { checked.insert(idx) }
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Image(systemName: checked.contains(idx) ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(checked.contains(idx) ? Color.accentColor : .secondary)
                        Text(ing.display)
                            .strikethrough(checked.contains(idx))
                            .foregroundStyle(checked.contains(idx) ? .secondary : .primary)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 7)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Divider()
            }
        }
    }

    private func stepsSection(_ r: RecipeDetail) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionTitle("Steps")
            ForEach(Array(r.steps.enumerated()), id: \.offset) { idx, step in
                if let sec = step.section, idx == 0 || r.steps[idx - 1].section != sec {
                    Text(sec.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary).padding(.top, 4)
                }
                HStack(alignment: .top, spacing: 12) {
                    Text("\(idx + 1)")
                        .font(.footnote.bold()).foregroundStyle(.white)
                        .frame(width: 26, height: 26)
                        .background(Color.accentColor, in: Circle())
                    Text(step.text).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    @ViewBuilder
    private func extrasSection(_ r: RecipeDetail) -> some View {
        sectionTitle("Nutrition")
        if let n = r.nutrition {
            NutritionGrid(n: n)
        } else if app.aiEnabled {
            Button {
                Task { await run("nutrition") { try await API.shared.nutrition(r.id) } }
            } label: { busyLabel("Estimate nutrition", key: "nutrition", icon: "chart.bar") }
            .buttonStyle(.bordered)
        } else {
            Text("Nutrition estimates need AI enabled on your server.").font(.footnote).foregroundStyle(.secondary)
        }

        sectionTitle("Sub-recipes")
        if let comps = r.components, !comps.isEmpty {
            NavigationLink { SubRecipeDiagramView(title: r.title, components: comps) } label: {
                Label("View breakdown (\(comps.count) parts)", systemImage: "point.3.connected.trianglepath.dotted")
            }
            .buttonStyle(.bordered)
        } else {
            Button {
                Task { await run("breakdown") { try await API.shared.breakdown(r.id) } }
            } label: { busyLabel("Break down into sub-recipes", key: "breakdown", icon: "point.3.connected.trianglepath.dotted") }
            .buttonStyle(.bordered)
        }
        if let error { Text(error).font(.footnote).foregroundStyle(.red) }
    }

    private func busyLabel(_ title: String, key: String, icon: String) -> some View {
        HStack {
            if busy == key { ProgressView().controlSize(.small) } else { Image(systemName: icon) }
            Text(title)
        }
    }

    @ToolbarContentBuilder
    private func toolbar(_ r: RecipeDetail) -> some ToolbarContent {
        ToolbarItemGroup(placement: .topBarTrailing) {
            if r.isOwner {
                Button {
                    Task {
                        if let u = try? await API.shared.patchRecipe(r.id, ["favorite": AnyEncodable(!r.favorite)]) { recipe = u }
                        app.libraryVersion += 1
                    }
                } label: { Image(systemName: r.favorite ? "heart.fill" : "heart") }
            }
            Menu {
                Button { reader.speakRecipe(r) } label: { Label("Read aloud", systemImage: "speaker.wave.2") }
                if r.isOwner {
                    Button { showShopping = true } label: { Label("Add to shopping list", systemImage: "cart.badge.plus") }
                    Button { showCollections = true } label: { Label("Add to collection", systemImage: "folder.badge.plus") }
                    Button { showLog = true } label: { Label("Log that I cooked this", systemImage: "fork.knife") }
                    Button { showNotes = true } label: { Label("Edit my notes", systemImage: "note.text") }
                }
                Divider()
                if let s = r.shareUrl, let u = URL(string: s) {
                    Button { shareItems = ShareItems(items: [u]) } label: { Label("Share link", systemImage: "square.and.arrow.up") }
                }
                Button {
                    Task {
                        if let url = await RecipePDF.makeFile(r) { shareItems = ShareItems(items: [url]) }
                    }
                } label: { Label("Export PDF", systemImage: "doc.richtext") }
                Button { Task { await RecipePDF.print(r) } } label: { Label("Print", systemImage: "printer") }
                if r.isOwner {
                    Divider()
                    Button { showEdit = true } label: { Label("Edit recipe", systemImage: "pencil") }
                    Button { Task { await run("cat") { try await API.shared.recategorize(r.id) } } } label: {
                        Label("Re-categorize", systemImage: "tag")
                    }
                    Button(role: .destructive) { confirmDelete = true } label: { Label("Delete", systemImage: "trash") }
                }
            } label: { Image(systemName: "ellipsis.circle") }
        }
    }

    // MARK: - Data

    private func load() async {
        if recipe == nil, let preloaded, servings == nil, scale == nil, units == nil {
            recipe = preloaded
            return
        }
        do {
            if let shareToken, !(recipe?.isOwner ?? false) {
                recipe = try await API.shared.sharedRecipe(token: shareToken, servings: servings, scale: scale, units: units)
            } else {
                recipe = try await API.shared.recipe(recipeId, servings: servings, scale: scale, units: units)
            }
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func run(_ key: String, _ op: @escaping () async throws -> RecipeDetail) async {
        busy = key
        defer { busy = nil }
        do {
            recipe = try await op()
            error = nil
            app.libraryVersion += 1
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct NutritionGrid: View {
    let n: Nutrition

    var body: some View {
        let rows: [(String, Double?, String)] = [
            ("Calories", n.calories, ""), ("Protein", n.proteinG, "g"), ("Carbs", n.carbsG, "g"),
            ("Fat", n.fatG, "g"), ("Fiber", n.fiberG, "g"), ("Sugar", n.sugarG, "g"), ("Sodium", n.sodiumMg, "mg"),
        ]
        VStack(alignment: .leading, spacing: 6) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 90), spacing: 8)], spacing: 8) {
                ForEach(rows.filter { $0.1 != nil }, id: \.0) { row in
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(formatNumber(row.1!))\(row.2)").font(.headline)
                        Text(row.0).font(.caption).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
                }
            }
            Text(n.source == "estimated" ? "Per serving, estimated by AI\(n.assumedServings.map { " (assuming \(formatNumber($0)) servings)" } ?? "")."
                                         : "Per serving, from the publisher.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }
}

struct NotesEditor: View {
    @State var text: String
    let onSave: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            TextEditor(text: $text)
                .padding()
                .navigationTitle("My notes")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button("Save") { onSave(text); dismiss() } }
                }
        }
    }
}

struct ShareItems: Identifiable {
    let id = UUID()
    let items: [Any]
}

struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

struct AddToShoppingView: View {
    let recipe: RecipeDetail
    @Environment(\.dismiss) private var dismiss
    @Environment(AppState.self) private var app
    @State private var selected: Set<Int> = []
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(Array(recipe.ingredients.enumerated()), id: \.offset) { idx, ing in
                        Button {
                            if selected.contains(idx) { selected.remove(idx) } else { selected.insert(idx) }
                        } label: {
                            HStack {
                                Image(systemName: selected.contains(idx) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(selected.contains(idx) ? Color.accentColor : .secondary)
                                Text(ing.display).foregroundStyle(.primary)
                            }
                        }
                    }
                } footer: {
                    Text("Untick what you already have. Duplicates across recipes are merged.")
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Add to shopping list")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear { selected = Set(recipe.ingredients.indices) }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add \(selected.count)") {
                        Task {
                            busy = true
                            do {
                                _ = try await API.shared.addRecipeToShopping(recipe.id, servings: recipe.currentServings,
                                                                              indexes: selected.sorted())
                                dismiss()
                            } catch { self.error = error.localizedDescription }
                            busy = false
                        }
                    }
                    .disabled(selected.isEmpty || busy)
                }
            }
        }
    }
}

struct CollectionPickerView: View {
    let recipeId: Int
    @State var selected: Set<Int>
    var onDone: () -> Void = {}
    @Environment(\.dismiss) private var dismiss
    @State private var collections: [RecipeCollection] = []
    @State private var newName = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        TextField("New collection", text: $newName)
                        Button("Add") {
                            let name = newName
                            newName = ""
                            Task {
                                if let c = try? await API.shared.createCollection(name) {
                                    _ = try? await API.shared.addToCollection(c.id, recipe: recipeId)
                                    selected.insert(c.id)
                                    await load()
                                }
                            }
                        }
                        .disabled(newName.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                Section {
                    ForEach(collections) { c in
                        Button {
                            Task { await toggle(c) }
                        } label: {
                            HStack {
                                Text(c.name).foregroundStyle(.primary)
                                Spacer()
                                if selected.contains(c.id) { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Collections")
            .navigationBarTitleDisplayMode(.inline)
            .task { await load() }
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { onDone(); dismiss() } }
            }
        }
    }

    private func load() async {
        collections = (try? await API.shared.collections()) ?? collections
    }

    private func toggle(_ c: RecipeCollection) async {
        if selected.contains(c.id) {
            _ = try? await API.shared.removeFromCollection(c.id, recipe: recipeId)
            selected.remove(c.id)
        } else {
            _ = try? await API.shared.addToCollection(c.id, recipe: recipeId)
            selected.insert(c.id)
        }
    }
}
