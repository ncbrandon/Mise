import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// "Save to Mise" in the iOS share sheet: works from Safari, YouTube, TikTok, Instagram, Photos and Files.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.close = { [weak self] in self?.extensionContext?.completeRequest(returningItems: nil) }
        let host = UIHostingController(rootView: ShareView(model: model))
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        Task { await model.run(items: extensionContext?.inputItems as? [NSExtensionItem] ?? []) }
    }
}

@MainActor
@Observable
final class ShareModel {
    enum State { case working(String), done(RecipeDetail, duplicate: Bool), failed(String) }
    var state: State = .working("Getting ready…")
    var close: () -> Void = {}

    func run(items: [NSExtensionItem]) async {
        guard SharedConfig.serverURL != nil, SharedConfig.token != nil else {
            state = .failed("Open Mise and sign in to your server first.")
            return
        }
        let providers = items.flatMap { $0.attachments ?? [] }
        do {
            // 1. URL (Safari, YouTube, TikTok, Instagram...)
            if let url = await loadURL(providers) {
                state = .working(isVideo(url) ? "Watching the video…" : "Reading the recipe…")
                let res = try await API.shared.importURL(url)
                return finish(res)
            }
            // 2. Images (Photos, screenshots)
            let images = await loadImages(providers)
            if !images.isEmpty {
                state = .working("Reading your photo…")
                return finish(try await API.shared.importPhotos(images))
            }
            // 3. Files (PDF, Word)
            if let file = await loadFile(providers) {
                state = .working("Reading your document…")
                return finish(try await API.shared.importDocument(file.0, filename: file.1, mime: file.2))
            }
            // 4. Plain text (Notes, Messages); may contain a link
            if let text = await loadText(providers) ?? items.compactMap({ $0.attributedContentText?.string }).first {
                if let url = Self.firstURL(in: text) {
                    state = .working(isVideo(url) ? "Watching the video…" : "Reading the recipe…")
                    return finish(try await API.shared.importURL(url))
                }
                state = .working("Writing up your recipe…")
                return finish(try await API.shared.importText(text))
            }
            state = .failed("Nothing Mise can import was shared.")
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func finish(_ res: ImportResponse) {
        if let r = res.recipe { state = .done(r, duplicate: res.duplicate ?? false) } else { state = .failed("No recipe found.") }
    }

    private func isVideo(_ url: String) -> Bool {
        ["youtu", "tiktok", "instagram", "facebook", "fb.watch", "vimeo"].contains { url.contains($0) }
    }

    static func firstURL(in s: String) -> String? {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        return detector?.firstMatch(in: s, range: NSRange(s.startIndex..., in: s))?.url?.absoluteString
    }

    // MARK: - Loading attachments

    private func loadURL(_ providers: [NSItemProvider]) async -> String? {
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            if let item = try? await p.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) {
                if let url = item as? URL, !url.isFileURL { return url.absoluteString }
                if let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil), !url.isFileURL {
                    return url.absoluteString
                }
            }
        }
        return nil
    }

    private func loadText(_ providers: [NSItemProvider]) async -> String? {
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            if let s = try? await p.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) as? String { return s }
        }
        return nil
    }

    private func loadImages(_ providers: [NSItemProvider]) async -> [Data] {
        var out: [Data] = []
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
            guard let item = try? await p.loadItem(forTypeIdentifier: UTType.image.identifier, options: nil) else { continue }
            var image: UIImage?
            if let url = item as? URL, let data = try? Data(contentsOf: url) { image = UIImage(data: data) }
            else if let data = item as? Data { image = UIImage(data: data) }
            else if let img = item as? UIImage { image = img }
            if let image, let jpeg = Self.jpeg(image) { out.append(jpeg) }
            if out.count == 6 { break }
        }
        return out
    }

    private func loadFile(_ providers: [NSItemProvider]) async -> (Data, String, String)? {
        let types: [UTType] = [.pdf, UTType(filenameExtension: "docx") ?? .data, .rtf, .html]
        for p in providers {
            for t in types where p.hasItemConformingToTypeIdentifier(t.identifier) {
                if let item = try? await p.loadItem(forTypeIdentifier: t.identifier, options: nil) {
                    if let url = item as? URL, let data = try? Data(contentsOf: url) {
                        return (data, url.lastPathComponent, t.preferredMIMEType ?? "application/octet-stream")
                    }
                    if let data = item as? Data {
                        return (data, "document.\(t.preferredFilenameExtension ?? "bin")", t.preferredMIMEType ?? "application/octet-stream")
                    }
                }
            }
        }
        return nil
    }

    static func jpeg(_ img: UIImage, maxSide: CGFloat = 2000) -> Data? {
        let scale = min(1, maxSide / max(img.size.width, img.size.height))
        let size = CGSize(width: img.size.width * scale, height: img.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return UIGraphicsImageRenderer(size: size, format: format)
            .image { _ in img.draw(in: CGRect(origin: .zero, size: size)) }
            .jpegData(compressionQuality: 0.8)
    }
}

struct ShareView: View {
    let model: ShareModel

    var body: some View {
        NavigationStack {
            VStack(spacing: 18) {
                switch model.state {
                case .working(let message):
                    ProgressView().controlSize(.large)
                    Text(message).font(.headline)
                    Text("Videos and photos can take up to a minute.").font(.footnote).foregroundStyle(.secondary)
                case .done(let r, let duplicate):
                    if let s = r.imageUrl, let u = URL(string: s) {
                        AsyncImage(url: u) { img in img.resizable().scaledToFill() } placeholder: { Color.gray.opacity(0.15) }
                            .frame(width: 140, height: 105).clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    Image(systemName: "checkmark.circle.fill").font(.system(size: 44)).foregroundStyle(.green)
                    Text(duplicate ? "Already in your recipes" : "Saved to Mise").font(.headline)
                    Text(r.title).font(.title3.bold()).multilineTextAlignment(.center)
                    Text("\(r.ingredients.count) ingredients · \(r.steps.count) steps").foregroundStyle(.secondary)
                case .failed(let message):
                    Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 44)).foregroundStyle(.orange)
                    Text("Couldn't save").font(.headline)
                    Text(message).multilineTextAlignment(.center).foregroundStyle(.secondary)
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle("Mise")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { model.close() } }
            }
        }
    }
}
