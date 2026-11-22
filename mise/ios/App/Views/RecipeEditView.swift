import PhotosUI
import SwiftUI

/// Create or edit a recipe. Ingredients and steps are edited as plain text, one per line;
/// a short line ending in ":" starts a group/section ("Sauce:").
struct RecipeEditView: View {
    let existing: RecipeDetail?
    let onSaved: (RecipeDetail) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var summary = ""
    @State private var servings = ""
    @State private var servingsText = ""
    @State private var prep = ""
    @State private var cook = ""
    @State private var total = ""
    @State private var ingredients = ""
    @State private var steps = ""
    @State private var categories = ""
    @State private var cuisine = ""
    @State private var notes = ""
    @State private var imageUrl: String?
    @State private var isPublic = true
    @State private var photo: PhotosPickerItem?
    @State private var busy = false
    @State private var error: String?
    @State private var loaded = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Title", text: $title, axis: .vertical).font(.headline)
                    TextField("Short description", text: $summary, axis: .vertical)
                    HStack {
                        RemoteImage(url: imageUrl).frame(width: 64, height: 64).clipShape(RoundedRectangle(cornerRadius: 8))
                        PhotosPicker(selection: $photo, matching: .images) {
                            Text(imageUrl == nil ? "Add photo" : "Change photo")
                        }
                    }
                }
                Section("Servings & time") {
                    HStack { Text("Servings"); TextField("4", text: $servings).keyboardType(.decimalPad).multilineTextAlignment(.trailing) }
                    HStack { Text("Yield label"); TextField("e.g. 12 cookies", text: $servingsText).multilineTextAlignment(.trailing) }
                    HStack { Text("Prep (min)"); TextField("15", text: $prep).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
                    HStack { Text("Cook (min)"); TextField("30", text: $cook).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
                    HStack { Text("Total (min)"); TextField("auto", text: $total).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
                }
                Section {
                    TextEditor(text: $ingredients).frame(minHeight: 180).font(.body.monospaced())
                } header: { Text("Ingredients") } footer: {
                    Text("One per line, e.g. “2 cups flour”. A line like “Sauce:” starts a group.")
                }
                Section {
                    TextEditor(text: $steps).frame(minHeight: 220)
                } header: { Text("Steps") } footer: {
                    Text("One step per line. A short line ending in “:” starts a section.")
                }
                Section("Details") {
                    TextField("Categories (comma separated, blank = automatic)", text: $categories)
                    TextField("Cuisine", text: $cuisine)
                    Toggle("Visible to friends", isOn: $isPublic)
                }
                Section("My notes") { TextEditor(text: $notes).frame(minHeight: 80) }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }
            .navigationTitle(existing == nil ? "New recipe" : "Edit recipe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Save") { Task { await save() } }
                            .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .task {
                // Load the unscaled, unconverted version so edits don't bake in a unit conversion.
                guard !loaded else { return }
                if let r = existing, let original = try? await API.shared.recipe(r.id, units: "original") {
                    fill(original)
                } else {
                    fill(existing)
                }
            }
            .onChange(of: photo) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data),
                       let jpeg = img.resizedJPEG(maxSide: 1600) {
                        busy = true
                        imageUrl = try? await API.shared.uploadMedia(jpeg: jpeg)
                        busy = false
                    }
                }
            }
        }
    }

    private func fill(_ recipe: RecipeDetail?) {
        guard !loaded else { return }
        loaded = true
        guard let r = recipe else { return }
        title = r.title
        summary = r.description ?? ""
        servings = r.servings.map(formatNumber) ?? ""
        servingsText = r.servingsText ?? ""
        prep = r.prepTime.map(String.init) ?? ""
        cook = r.cookTime.map(String.init) ?? ""
        total = r.totalTime.map(String.init) ?? ""
        imageUrl = r.imageUrl
        isPublic = r.isPublic
        notes = r.notes ?? ""
        cuisine = r.cuisine ?? ""
        categories = r.categories.joined(separator: ", ")
        // raw = original text, so edits never bake in scaling/conversion
        var lines: [String] = []
        var group: String? = nil
        for i in r.ingredients {
            if i.group != group {
                group = i.group
                if let g = group { lines.append((g.hasSuffix(":") ? g : g + ":")) }
            }
            lines.append(i.raw)
        }
        ingredients = lines.joined(separator: "\n")
        var slines: [String] = []
        var section: String? = nil
        for s in r.steps {
            if s.section != section {
                section = s.section
                if let sec = section { slines.append(sec + ":") }
            }
            slines.append(s.text)
        }
        steps = slines.joined(separator: "\n")
    }

    private func parsedSteps() -> [RecipeStep] {
        var out: [RecipeStep] = []
        var section: String? = nil
        for line in steps.components(separatedBy: .newlines) {
            var t = line.trimmingCharacters(in: .whitespaces)
            guard !t.isEmpty else { continue }
            if t.hasSuffix(":") && t.count < 40 {
                section = String(t.dropLast())
                continue
            }
            if let r = t.range(of: #"^(\d+[.)]|step\s*\d+[:.)]?)\s*"#, options: [.regularExpression, .caseInsensitive]) {
                t.removeSubrange(r)
            }
            out.append(RecipeStep(text: t, section: section))
        }
        return out
    }

    private func save() async {
        busy = true
        defer { busy = false }
        let cats = categories.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let input = RecipeInput(
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            description: summary.isEmpty ? nil : summary,
            imageUrl: imageUrl,
            sourceUrl: existing?.sourceUrl,
            author: existing?.author,
            servings: Double(servings.replacingOccurrences(of: ",", with: ".")),
            servingsText: servingsText.isEmpty ? nil : servingsText,
            prepTime: Int(prep), cookTime: Int(cook), totalTime: Int(total),
            ingredients: ingredients.components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
                .map { IngredientInput(raw: $0, group: nil) },
            steps: parsedSteps(),
            categories: cats.isEmpty ? (existing == nil ? nil : []) : cats,
            cuisine: cuisine.isEmpty ? nil : cuisine,
            notes: notes.isEmpty ? nil : notes,
            rating: existing?.rating,
            favorite: existing?.favorite ?? false,
            isPublic: isPublic
        )
        do {
            let saved = existing == nil ? try await API.shared.createRecipe(input)
                                        : try await API.shared.updateRecipe(existing!.id, input)
            onSaved(saved)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
