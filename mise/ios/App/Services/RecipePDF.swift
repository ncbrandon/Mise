import UIKit

/// Clean, printable PDFs rendered on-device.
@MainActor
enum RecipePDF {
    static func html(_ r: RecipeDetail, imageData: Data?) -> String {
        func esc(_ s: String) -> String {
            s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
                .replacingOccurrences(of: ">", with: "&gt;")
        }
        var meta: [String] = []
        if let s = r.currentServings ?? r.servings { meta.append("Serves \(formatNumber(s))") }
        if let t = formatMinutes(r.prepTime) { meta.append("Prep \(t)") }
        if let t = formatMinutes(r.cookTime) { meta.append("Cook \(t)") }
        if let t = formatMinutes(r.totalTime) { meta.append("Total \(t)") }

        var ings = ""
        var group: String? = nil
        for i in r.ingredients {
            if i.group != group {
                group = i.group
                if let g = group { ings += "</ul><h3>\(esc(g))</h3><ul>" }
            }
            ings += "<li>\(esc(i.display))</li>"
        }
        var steps = ""
        var section: String? = nil
        for (n, s) in r.steps.enumerated() {
            if s.section != section {
                section = s.section
                if let sec = section { steps += "</ol><h3>\(esc(sec))</h3><ol start=\"\(n + 1)\">" }
            }
            steps += "<li>\(esc(s.text))</li>"
        }
        let img = imageData.map { "<img src=\"data:image/jpeg;base64,\($0.base64EncodedString())\">" } ?? ""
        let notes = (r.notes?.isEmpty == false) ? "<h2>Notes</h2><p>\(esc(r.notes!))</p>" : ""
        let source = r.sourceUrl.map { "<p class=\"src\">Source: \(esc($0))</p>" } ?? ""
        return """
        <html><head><meta charset="utf-8"><style>
        body { font-family: -apple-system, Helvetica; font-size: 11.5pt; color: #1f1b16; line-height: 1.45; }
        h1 { font-family: Georgia, serif; font-size: 24pt; margin: 0 0 4pt; }
        h2 { font-family: Georgia, serif; font-size: 14pt; margin: 16pt 0 6pt; border-bottom: 1px solid #ddd; padding-bottom: 3pt; }
        h3 { font-size: 9pt; text-transform: uppercase; letter-spacing: .06em; color: #6f665b; margin: 10pt 0 2pt; }
        .meta { color: #6f665b; font-size: 10pt; }
        img { width: 100%; max-height: 220pt; object-fit: cover; border-radius: 8pt; margin: 8pt 0; }
        ul { padding-left: 16pt; } li { margin: 2pt 0; } ol li { margin: 5pt 0; }
        .src { color: #999; font-size: 8.5pt; margin-top: 18pt; }
        </style></head><body>
        <h1>\(esc(r.title))</h1>
        <div class="meta">\(meta.joined(separator: " · "))</div>
        \(img)
        \(r.description.map { "<p>\(esc($0))</p>" } ?? "")
        <h2>Ingredients</h2><ul>\(ings)</ul>
        <h2>Steps</h2><ol>\(steps)</ol>
        \(notes)
        \(source)
        </body></html>
        """
    }

    private static func image(_ r: RecipeDetail) async -> Data? {
        guard let s = r.imageUrl, let u = URL(string: s),
              let result = try? await URLSession.shared.data(from: u),
              let img = UIImage(data: result.0) else { return nil }
        let maxW: CGFloat = 1000
        let scale = min(1, maxW / img.size.width)
        let size = CGSize(width: img.size.width * scale, height: img.size.height * scale)
        return UIGraphicsImageRenderer(size: size).image { _ in img.draw(in: CGRect(origin: .zero, size: size)) }
            .jpegData(compressionQuality: 0.75)
    }

    static func pdfData(_ r: RecipeDetail) async -> Data {
        let markup = html(r, imageData: await image(r))
        let formatter = UIMarkupTextPrintFormatter(markupText: markup)
        let renderer = UIPrintPageRenderer()
        renderer.addPrintFormatter(formatter, startingAtPageAt: 0)
        let paper = CGRect(x: 0, y: 0, width: 612, height: 792)  // US Letter in points
        renderer.setValue(NSValue(cgRect: paper), forKey: "paperRect")
        renderer.setValue(NSValue(cgRect: paper.insetBy(dx: 48, dy: 54)), forKey: "printableRect")
        let data = NSMutableData()
        UIGraphicsBeginPDFContextToData(data, paper, [kCGPDFContextTitle as String: r.title])
        renderer.prepare(forDrawingPages: NSRange(location: 0, length: renderer.numberOfPages))
        for page in 0..<renderer.numberOfPages {
            UIGraphicsBeginPDFPage()
            renderer.drawPage(at: page, in: UIGraphicsGetPDFContextBounds())
        }
        UIGraphicsEndPDFContext()
        return data as Data
    }

    static func makeFile(_ r: RecipeDetail) async -> URL? {
        let data = await pdfData(r)
        let safe = r.title.components(separatedBy: CharacterSet.alphanumerics.union(.whitespaces).inverted).joined()
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(safe.isEmpty ? "Recipe" : safe).pdf")
        do {
            try data.write(to: url)
            return url
        } catch {
            return nil
        }
    }

    static func print(_ r: RecipeDetail) async {
        let controller = UIPrintInteractionController.shared
        let info = UIPrintInfo(dictionary: nil)
        info.outputType = .general
        info.jobName = r.title
        controller.printInfo = info
        controller.printingItem = await pdfData(r)
        controller.present(animated: true)
    }
}
