import SwiftUI
import UserNotifications

/// Full-screen, one-step-at-a-time cooking mode. Keeps the screen on, reads steps aloud and runs timers.
struct CookModeView: View {
    let recipe: RecipeDetail
    @Environment(\.dismiss) private var dismiss
    @State private var index = 0
    @State private var readAloud = UserDefaults.standard.bool(forKey: "cookReadAloud")
    @State private var showIngredients = false
    @State private var reader = SpeechReader()
    @State private var timers = CookTimers()

    private var steps: [RecipeStep] { recipe.steps.isEmpty ? [RecipeStep(text: "No steps for this recipe.", section: nil)] : recipe.steps }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ProgressView(value: Double(index + 1), total: Double(steps.count))
                    .padding(.horizontal)
                if !timers.active.isEmpty { timerBar }
                TabView(selection: $index) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { i, step in
                        stepPage(i, step).tag(i)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                controls
            }
            .navigationTitle(recipe.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button { showIngredients = true } label: { Image(systemName: "list.bullet") }
                        .accessibilityLabel("Ingredients")
                    Button {
                        readAloud.toggle()
                        UserDefaults.standard.set(readAloud, forKey: "cookReadAloud")
                        if readAloud { speakCurrent() } else { reader.stop() }
                    } label: { Image(systemName: readAloud ? "speaker.wave.2.fill" : "speaker.slash") }
                        .accessibilityLabel("Read steps aloud")
                }
            }
            .sheet(isPresented: $showIngredients) { ingredientsSheet.presentationDetents([.medium, .large]) }
        }
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            if readAloud { speakCurrent() }
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            reader.stop()
        }
        .onChange(of: index) { _, _ in if readAloud { speakCurrent() } }
    }

    private func stepPage(_ i: Int, _ step: RecipeStep) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if let sec = step.section {
                    Text(sec.uppercased()).font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                }
                Text("Step \(i + 1) of \(steps.count)").font(.subheadline).foregroundStyle(Color.accentColor)
                Text(step.text)
                    .font(.system(size: 28, weight: .medium, design: .serif))
                    .fixedSize(horizontal: false, vertical: true)
                let used = ingredientsMentioned(in: step.text)
                if !used.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(used, id: \.self) { Text("• \($0)").foregroundStyle(.secondary) }
                    }
                }
                ForEach(CookTimers.durations(in: step.text), id: \.self) { secs in
                    Button {
                        timers.start(label: "Step \(i + 1)", seconds: secs, recipe: recipe.title)
                    } label: {
                        Label("Start \(CookTimers.format(secs)) timer", systemImage: "timer")
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(24)
            .frame(maxWidth: 700, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    private var controls: some View {
        HStack(spacing: 16) {
            Button { withAnimation { index = max(0, index - 1) } } label: {
                Label("Back", systemImage: "chevron.left").frame(maxWidth: .infinity).padding(.vertical, 8)
            }
            .buttonStyle(.bordered)
            .disabled(index == 0)
            Button {
                if index < steps.count - 1 { withAnimation { index += 1 } } else { dismiss() }
            } label: {
                Label(index < steps.count - 1 ? "Next" : "Finish", systemImage: index < steps.count - 1 ? "chevron.right" : "checkmark")
                    .frame(maxWidth: .infinity).padding(.vertical, 8)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    private var timerBar: some View {
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(timers.active) { t in
                        let left = max(0, Int(t.end.timeIntervalSince(ctx.date)))
                        HStack(spacing: 6) {
                            Image(systemName: left == 0 ? "bell.fill" : "timer")
                            Text("\(t.label) · \(left == 0 ? "Done" : CookTimers.clock(left))").monospacedDigit()
                            Button { timers.cancel(t) } label: { Image(systemName: "xmark.circle.fill") }
                        }
                        .font(.subheadline.weight(.medium))
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(left == 0 ? Color.red.opacity(0.2) : Color.accentColor.opacity(0.15), in: Capsule())
                    }
                }
                .padding(.horizontal)
            }
            .padding(.vertical, 8)
        }
    }

    private var ingredientsSheet: some View {
        NavigationStack {
            List(Array(recipe.ingredients.enumerated()), id: \.offset) { _, ing in
                Text(ing.display)
            }
            .navigationTitle("Ingredients")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func speakCurrent() {
        guard steps.indices.contains(index) else { return }
        reader.speak("Step \(index + 1). \(steps[index].text)")
    }

    /// Ingredients whose main word appears in the step (helps when you're mid-step).
    private func ingredientsMentioned(in text: String) -> [String] {
        let lower = text.lowercased()
        return recipe.ingredients.filter { ing in
            let words = ing.name.lowercased().split(whereSeparator: { !$0.isLetter }).map(String.init).filter { $0.count > 3 }
            guard let key = words.last else { return false }
            let stem = key.hasSuffix("s") ? String(key.dropLast()) : key
            return lower.contains(stem)
        }
        .map(\.display)
    }
}

@MainActor
@Observable
final class CookTimers {
    struct Item: Identifiable, Hashable {
        let id = UUID()
        let label: String
        let end: Date
    }

    var active: [Item] = []

    func start(label: String, seconds: Int, recipe: String) {
        let item = Item(label: label, end: Date().addingTimeInterval(TimeInterval(seconds)))
        active.append(item)
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = "Timer done"
            content.body = "\(recipe) — \(label)"
            content.sound = .default
            let trigger = UNTimeIntervalNotificationTrigger(timeInterval: TimeInterval(max(1, seconds)), repeats: false)
            center.add(UNNotificationRequest(identifier: item.id.uuidString, content: content, trigger: trigger))
        }
    }

    func cancel(_ item: Item) {
        active.removeAll { $0.id == item.id }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [item.id.uuidString])
    }

    /// "bake 25-30 minutes", "simmer for 1 hour", "rest 10 mins" -> seconds (uses the upper bound of ranges)
    static func durations(in text: String) -> [Int] {
        let pattern = #"(\d+(?:[.,]\d+)?)\s*(?:(?:-|–|to)\s*(\d+(?:[.,]\d+)?)\s*)?(hours?|hrs?|h\b|minutes?|mins?|seconds?|secs?)"#
        guard let rx = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) else { return [] }
        let ns = text as NSString
        var out: [Int] = []
        for m in rx.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            let a = Double(ns.substring(with: m.range(at: 1)).replacingOccurrences(of: ",", with: ".")) ?? 0
            let b = m.range(at: 2).location != NSNotFound
                ? Double(ns.substring(with: m.range(at: 2)).replacingOccurrences(of: ",", with: ".")) ?? a : a
            let unit = ns.substring(with: m.range(at: 3)).lowercased()
            let mult: Double = unit.hasPrefix("h") ? 3600 : unit.hasPrefix("s") ? 1 : 60
            let secs = Int(max(a, b) * mult)
            if secs > 0 && secs <= 24 * 3600 && !out.contains(secs) { out.append(secs) }
        }
        return out
    }

    static func clock(_ secs: Int) -> String {
        let h = secs / 3600, m = (secs % 3600) / 60, s = secs % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }

    static func format(_ secs: Int) -> String {
        let h = secs / 3600, m = (secs % 3600) / 60, s = secs % 60
        if h > 0 { return String(format: "%d:%02d:%02d", h, m, s) }
        if secs >= 60 && s == 0 { return "\(m) min" }
        return String(format: "%d:%02d", m, s)
    }
}
