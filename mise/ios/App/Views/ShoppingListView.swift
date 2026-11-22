import SwiftUI

struct ShoppingListView: View {
    @Environment(AppState.self) private var app
    @State private var list: ShoppingList?
    @State private var newItem = ""
    @State private var units: String?
    @State private var error: String?
    @State private var confirmClear = false
    @FocusState private var addFocused: Bool

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Image(systemName: "plus.circle.fill").foregroundStyle(Color.accentColor)
                        TextField("Add item, e.g. 2 lb apples", text: $newItem)
                            .focused($addFocused)
                            .submitLabel(.done)
                            .onSubmit { add() }
                    }
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
                if let list {
                    if list.aisles.isEmpty && list.checked.isEmpty {
                        ContentUnavailableView("Your list is empty", systemImage: "cart",
                                               description: Text("Add ingredients from any recipe with ••• → Add to shopping list."))
                    }
                    ForEach(list.aisles, id: \.aisle) { group in
                        Section(group.aisle) {
                            ForEach(group.items) { item in row(item) }
                                .onDelete { idx in delete(idx.map { group.items[$0] }) }
                        }
                    }
                    if !list.checked.isEmpty {
                        Section("In the cart") {
                            ForEach(list.checked) { item in row(item) }
                                .onDelete { idx in delete(idx.map { list.checked[$0] }) }
                        }
                    }
                }
            }
            .navigationTitle("Shopping")
            .refreshable { await load() }
            .task(id: units) { await load() }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Picker("Units", selection: Binding(get: { units ?? (app.units == "metric" ? "metric" : "imperial") },
                                                           set: { units = $0 })) {
                            Text("US / imperial").tag("imperial")
                            Text("Metric").tag("metric")
                        }
                        Button { mutate { try await API.shared.clearCheckedShopping() } } label: {
                            Label("Remove checked items", systemImage: "checkmark.circle")
                        }
                        Button(role: .destructive) { confirmClear = true } label: { Label("Clear list", systemImage: "trash") }
                        if let text = shareText {
                            ShareLink(item: text) { Label("Share list", systemImage: "square.and.arrow.up") }
                        }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
            .confirmationDialog("Clear the whole list?", isPresented: $confirmClear, titleVisibility: .visible) {
                Button("Clear list", role: .destructive) { mutate { try await API.shared.clearShopping() } }
            }
        }
    }

    private func row(_ item: ShoppingItem) -> some View {
        Button {
            mutate { try await API.shared.setShoppingChecked(item.id, !item.checked) }
        } label: {
            HStack(alignment: .firstTextBaseline) {
                Image(systemName: item.checked ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(item.checked ? Color.accentColor : .secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.display)
                        .strikethrough(item.checked)
                        .foregroundStyle(item.checked ? .secondary : .primary)
                    if !item.sources.isEmpty {
                        Text(item.sources.joined(separator: ", ")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
            }
        }
        .sensoryFeedback(.selection, trigger: item.checked)
    }

    private var shareText: String? {
        guard let list, !list.aisles.isEmpty else { return nil }
        return list.aisles.map { g in
            "\(g.aisle)\n" + g.items.map { "• \($0.display)" }.joined(separator: "\n")
        }.joined(separator: "\n\n")
    }

    private func add() {
        let text = newItem.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        newItem = ""
        addFocused = true
        mutate { try await API.shared.addShoppingItem(text) }
    }

    private func delete(_ items: [ShoppingItem]) {
        mutate {
            var last: ShoppingList?
            for i in items { last = try await API.shared.deleteShoppingItem(i.id) }
            if let last { return last }
            return try await API.shared.shopping(units: units)
        }
    }

    private func mutate(_ op: @escaping () async throws -> ShoppingList) {
        Task {
            do {
                _ = try await op()
                await load()
            } catch { self.error = error.localizedDescription }
        }
    }

    private func load() async {
        do {
            list = try await API.shared.shopping(units: units)
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
    }
}
