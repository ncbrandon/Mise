import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct ImportView: View {
    let initialURL: String?

    enum Mode: Hashable { case menu, link, text, voice }

    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var mode: Mode = .menu
    @State private var link = ""
    @State private var text = ""
    @State private var title = ""
    @State private var busy = false
    @State private var status = ""
    @State private var error: String?
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var showPhotos = false
    @State private var showCamera = false
    @State private var showFiles = false
    @State private var showManual = false
    @State private var dictation = Dictation()

    var body: some View {
        NavigationStack {
            Group {
                if busy {
                    VStack(spacing: 16) {
                        ProgressView().controlSize(.large)
                        Text(status).font(.headline)
                        Text("Video and photo imports can take up to a minute.").font(.footnote).foregroundStyle(.secondary)
                    }
                    .padding()
                } else {
                    switch mode {
                    case .menu: menu
                    case .link: linkForm
                    case .text: textForm
                    case .voice: voiceForm
                    }
                }
            }
            .navigationTitle("Add recipe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(mode == .menu ? "Cancel" : "Back") {
                        if mode == .menu || busy { dismiss() } else { dictation.stop(); mode = .menu }
                    }
                }
            }
            .photosPicker(isPresented: $showPhotos, selection: $photoItems, maxSelectionCount: 6, matching: .images)
            .onChange(of: photoItems) { _, items in
                guard !items.isEmpty else { return }
                Task { await importPhotoItems(items) }
            }
            .fullScreenCover(isPresented: $showCamera) {
                CameraPicker { image in
                    if let jpeg = image.resizedJPEG() { Task { await importPhotos([jpeg]) } }
                }
                .ignoresSafeArea()
            }
            .fileImporter(isPresented: $showFiles,
                          allowedContentTypes: [.pdf, .plainText, .rtf, .html, .image,
                                                UTType(filenameExtension: "docx") ?? .data, UTType(filenameExtension: "md") ?? .plainText]) { result in
                if case .success(let url) = result { Task { await importFile(url) } }
            }
            .sheet(isPresented: $showManual) {
                RecipeEditView(existing: nil) { created in
                    app.didImport(created)
                    dismiss()
                }
            }
            .onAppear {
                if let initialURL, link.isEmpty {
                    link = initialURL
                    Task { await importLink() }
                }
            }
        }
    }

    // MARK: - Screens

    private var menu: some View {
        List {
            Section {
                PasteButton(payloadType: String.self) { strings in
                    guard let s = strings.first else { return }
                    Task { @MainActor in
                        if let url = firstURL(in: s) {
                            link = url
                            await importLink()
                        } else {
                            text = s
                            mode = .text
                        }
                    }
                }
                .labelStyle(.titleAndIcon)
                .frame(maxWidth: .infinity, alignment: .leading)
                row("Paste a link", "Websites, YouTube, TikTok, Instagram", "link") { mode = .link }
            } footer: {
                Text("Faster: tap Share in Safari, YouTube, TikTok or Instagram and choose “Save to Mise”.")
            }
            Section("Create from") {
                row("Photos", "Cookbook pages, recipe cards, screenshots", "photo.on.rectangle", needsAI: true) { showPhotos = true }
                row("Camera", "Snap a cookbook page", "camera", needsAI: true) { showCamera = true }
                row("Voice", "Tell Mise the recipe", "mic", needsAI: false) { mode = .voice }
                row("Text", "Paste or type a recipe", "text.alignleft") { mode = .text }
                row("Document", "PDF, Word, text files", "doc") { showFiles = true }
                row("Write it myself", "Blank recipe", "square.and.pencil") { showManual = true }
            }
            if let error {
                Section { Text(error).foregroundStyle(.red) }
            }
            if !app.aiEnabled {
                Section {
                    Text("AI isn't configured on your server, so photo imports are off and video/text imports only work when the caption lists the recipe. Add an LLM key to the stack to unlock everything.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func row(_ title: String, _ subtitle: String, _ icon: String, needsAI: Bool = false,
                     action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: icon).font(.title3).frame(width: 30).foregroundStyle(Color.accentColor)
                VStack(alignment: .leading) {
                    Text(title).foregroundStyle(.primary)
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .disabled(needsAI && !app.aiEnabled)
    }

    private var linkForm: some View {
        Form {
            Section {
                TextField("https://…", text: $link, axis: .vertical)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } footer: {
                Text("Recipe websites work instantly. Videos are read from their captions, description and speech.")
            }
            if let error { Section { Text(error).foregroundStyle(.red) } }
            Section {
                Button("Import") { Task { await importLink() } }.disabled(link.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private var textForm: some View {
        Form {
            Section("Title (optional)") { TextField("Grandma's lasagna", text: $title) }
            Section {
                TextEditor(text: $text).frame(minHeight: 260)
            } header: { Text("Recipe") } footer: {
                Text(app.aiEnabled ? "Paste anything — Mise will tidy it up."
                                   : "Use “Ingredients” and “Instructions” headings for best results.")
            }
            if let error { Section { Text(error).foregroundStyle(.red) } }
            Section { Button("Create recipe") { Task { await importText(voice: false) } }.disabled(text.isEmpty) }
        }
    }

    private var voiceForm: some View {
        VStack(spacing: 18) {
            ScrollView {
                Text(dictation.transcript.isEmpty ? "Tap the microphone and describe the recipe: what it's called, the ingredients with amounts, then the steps." : dictation.transcript)
                    .foregroundStyle(dictation.transcript.isEmpty ? .secondary : .primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
            }
            .frame(maxHeight: .infinity)
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
            if let e = dictation.error ?? error { Text(e).foregroundStyle(.red).font(.footnote) }
            Button {
                Task { await dictation.toggle() }
            } label: {
                Image(systemName: dictation.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                    .font(.system(size: 72))
                    .foregroundStyle(dictation.isRecording ? .red : Color.accentColor)
                    .symbolEffect(.pulse, isActive: dictation.isRecording)
            }
            Button("Create recipe") {
                dictation.stop()
                text = dictation.transcript
                Task { await importText(voice: true) }
            }
            .buttonStyle(.borderedProminent)
            .disabled(dictation.transcript.isEmpty)
        }
        .padding()
    }

    // MARK: - Actions

    private func firstURL(in s: String) -> String? {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        let range = NSRange(s.startIndex..., in: s)
        return detector?.firstMatch(in: s, range: range)?.url?.absoluteString
    }

    private func perform(_ label: String, _ op: () async throws -> ImportResponse) async {
        error = nil
        status = label
        busy = true
        defer { busy = false }
        do {
            let res = try await op()
            if let r = res.recipe {
                app.didImport(r)
                dismiss()
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func importLink() async {
        let raw = link.trimmingCharacters(in: .whitespacesAndNewlines)
        let url = firstURL(in: raw) ?? raw
        guard !url.isEmpty else { return }
        let isVideo = ["youtu", "tiktok", "instagram", "facebook", "fb.watch", "vimeo"].contains { url.contains($0) }
        await perform(isVideo ? "Watching the video…" : "Reading the recipe…") { try await API.shared.importURL(url) }
    }

    private func importText(voice: Bool) async {
        await perform("Writing up your recipe…") {
            try await API.shared.importText(text, title: title.isEmpty ? nil : title, voice: voice)
        }
    }

    private func importPhotoItems(_ items: [PhotosPickerItem]) async {
        var jpegs: [Data] = []
        for item in items {
            if let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data),
               let jpeg = img.resizedJPEG() {
                jpegs.append(jpeg)
            }
        }
        photoItems = []
        guard !jpegs.isEmpty else { error = "Couldn't read those photos"; return }
        await importPhotos(jpegs)
    }

    private func importPhotos(_ jpegs: [Data]) async {
        await perform("Reading your photo…") { try await API.shared.importPhotos(jpegs) }
    }

    private func importFile(_ url: URL) async {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else { error = "Couldn't open that file"; return }
        let type = UTType(filenameExtension: url.pathExtension)
        if type?.conforms(to: .image) == true, let img = UIImage(data: data), let jpeg = img.resizedJPEG() {
            await importPhotos([jpeg])
            return
        }
        let mime = type?.preferredMIMEType ?? "application/octet-stream"
        await perform("Reading your document…") {
            try await API.shared.importDocument(data, filename: url.lastPathComponent, mime: mime)
        }
    }
}

extension UIImage {
    /// Downscale to a sensible size for upload (AI vision models don't need 48 MP).
    func resizedJPEG(maxSide: CGFloat = 2000, quality: CGFloat = 0.8) -> Data? {
        let longest = max(size.width, size.height)
        let scale = min(1, maxSide / longest)
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let img = UIGraphicsImageRenderer(size: target, format: format).image { _ in draw(in: CGRect(origin: .zero, size: target)) }
        return img.jpegData(compressionQuality: quality)
    }
}

struct CameraPicker: UIViewControllerRepresentable {
    let onImage: (UIImage) -> Void
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let c = UIImagePickerController()
        c.sourceType = UIImagePickerController.isSourceTypeAvailable(.camera) ? .camera : .photoLibrary
        c.delegate = context.coordinator
        return c
    }

    func updateUIViewController(_ vc: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraPicker
        init(_ p: CameraPicker) { parent = p }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let img = info[.originalImage] as? UIImage { parent.onImage(img) }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { parent.dismiss() }
    }
}
