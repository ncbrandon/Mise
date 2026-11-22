import SwiftUI

/// Shows a recipe as its sub-recipes flowing into the finished dish.
struct SubRecipeDiagramView: View {
    let title: String
    let components: [RecipeComponent]

    /// Components ordered so that everything feeding into X comes before X.
    private var ordered: [RecipeComponent] {
        var result: [RecipeComponent] = []
        var remaining = components
        var guardCount = 0
        while !remaining.isEmpty && guardCount < 50 {
            guardCount += 1
            let names = Set(remaining.map(\.name))
            let ready = remaining.filter { c in
                !remaining.contains { $0.feedsInto == c.name && $0.name != c.name && names.contains($0.name) }
            }
            if ready.isEmpty { result += remaining; break }
            result += ready
            remaining.removeAll { r in ready.contains { $0.name == r.name } }
        }
        return result
    }

    private var finalName: String {
        components.first { $0.feedsInto == nil }?.name ?? title
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                overview.padding(.bottom, 20)
                ForEach(Array(ordered.enumerated()), id: \.offset) { idx, c in
                    card(c, isFinal: c.feedsInto == nil)
                    if idx < ordered.count - 1 {
                        Image(systemName: "arrow.down").font(.title3).foregroundStyle(.secondary).padding(.vertical, 8)
                    }
                }
            }
            .padding()
        }
        .navigationTitle("Breakdown")
        .navigationBarTitleDisplayMode(.inline)
    }

    /// Compact map: every part pointing at what it feeds into.
    private var overview: some View {
        VStack(spacing: 10) {
            let parts = ordered.filter { $0.feedsInto != nil }
            FlowLayout(spacing: 8) {
                ForEach(parts, id: \.name) { c in
                    Text(c.name).font(.subheadline.weight(.medium))
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .background(Color.accentColor.opacity(0.14), in: Capsule())
                }
            }
            if !parts.isEmpty {
                Image(systemName: "arrow.down.forward.and.arrow.up.backward").rotationEffect(.degrees(45))
                    .foregroundStyle(.secondary)
            }
            Text(finalName).font(.headline).foregroundStyle(.white)
                .padding(.horizontal, 16).padding(.vertical, 9)
                .background(Color.accentColor, in: Capsule())
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func card(_ c: RecipeComponent, isFinal: Bool) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(c.name).font(.system(.title3, design: .serif).bold())
                Spacer()
                if let into = c.feedsInto {
                    Text("→ \(into)").font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("Finish").font(.caption.bold()).foregroundStyle(Color.accentColor)
                }
            }
            if !c.ingredients.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(c.ingredients, id: \.self) { Text("• \($0)").font(.subheadline) }
                }
            }
            if !c.steps.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(c.steps.enumerated()), id: \.offset) { i, s in
                        HStack(alignment: .top) {
                            Text("\(i + 1).").font(.subheadline.bold()).foregroundStyle(Color.accentColor)
                            Text(s).font(.subheadline)
                        }
                    }
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).strokeBorder(isFinal ? Color.accentColor : Color(.separator), lineWidth: isFinal ? 2 : 1))
    }
}

/// Simple wrapping layout for chips.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x + s.width > maxWidth && x > 0 { x = 0; y += rowHeight + spacing; rowHeight = 0 }
            x += s.width + spacing
            widest = max(widest, x - spacing)
            rowHeight = max(rowHeight, s.height)
        }
        return CGSize(width: min(widest, maxWidth), height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        // centre each row
        var rows: [[(LayoutSubview, CGSize)]] = [[]]
        var x: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x + s.width > bounds.width && x > 0 { rows.append([]); x = 0 }
            rows[rows.count - 1].append((v, s))
            x += s.width + spacing
        }
        var y = bounds.minY
        for row in rows {
            let width = row.reduce(0) { $0 + $1.1.width } + spacing * CGFloat(max(0, row.count - 1))
            var cx = bounds.minX + (bounds.width - width) / 2
            let h = row.map(\.1.height).max() ?? 0
            for (v, s) in row {
                v.place(at: CGPoint(x: cx, y: y), proposal: ProposedViewSize(s))
                cx += s.width + spacing
            }
            y += h + spacing
        }
    }
}
