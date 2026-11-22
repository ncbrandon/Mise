import AVFoundation
import Speech
import SwiftUI

/// Reads recipes aloud with the best installed voice (Premium/Enhanced voices sound far more natural;
/// download them in Settings → Accessibility → Spoken Content → Voices).
@MainActor
@Observable
final class SpeechReader: NSObject, AVSpeechSynthesizerDelegate {
    private let synth = AVSpeechSynthesizer()
    var isSpeaking = false

    override init() {
        super.init()
        synth.delegate = self
    }

    static func bestVoice() -> AVSpeechSynthesisVoice? {
        let lang = Locale.current.language.languageCode?.identifier ?? "en"
        let preferred = UserDefaults.standard.string(forKey: "voiceIdentifier")
        if let preferred, let v = AVSpeechSynthesisVoice(identifier: preferred) { return v }
        let voices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix(lang) }
        let regional = voices.filter { $0.language == AVSpeechSynthesisVoice.currentLanguageCode() }
        let pool = regional.isEmpty ? voices : regional
        return pool.max { a, b in a.quality.rawValue < b.quality.rawValue }
            ?? AVSpeechSynthesisVoice(language: AVSpeechSynthesisVoice.currentLanguageCode())
    }

    func speak(_ text: String) {
        stop()
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? AVAudioSession.sharedInstance().setActive(true)
        let u = AVSpeechUtterance(string: text)
        u.voice = Self.bestVoice()
        u.rate = AVSpeechUtteranceDefaultSpeechRate * 0.95
        u.postUtteranceDelay = 0.2
        isSpeaking = true
        synth.speak(u)
    }

    func speakRecipe(_ r: RecipeDetail) {
        var parts = [r.title + "."]
        parts.append("Ingredients.")
        parts += r.ingredients.map { $0.display + "." }
        parts.append("Steps.")
        parts += r.steps.enumerated().map { "Step \($0.offset + 1). \($0.element.text)" }
        speak(parts.joined(separator: " "))
    }

    func stop() {
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        isSpeaking = false
    }

    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }
}

/// Live dictation for "tell me your recipe" imports.
@MainActor
@Observable
final class Dictation {
    var transcript = ""
    var isRecording = false
    var error: String?

    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var committed = ""  // text from earlier recognition sessions (they time out after ~1 min)

    func toggle() async {
        if isRecording { stop() } else { await start() }
    }

    func start() async {
        error = nil
        let speechOK = await withCheckedContinuation { c in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        let micOK = await AVAudioApplication.requestRecordPermission()
        guard speechOK, micOK else {
            error = "Allow microphone and speech recognition in Settings to dictate."
            return
        }
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else {
            error = "Speech recognition isn't available right now."
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let req = SFSpeechAudioBufferRecognitionRequest()
            req.shouldReportPartialResults = true
            req.addsPunctuation = true
            if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
            request = req

            let input = engine.inputNode
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
                req.append(buffer)
            }
            engine.prepare()
            try engine.start()
            isRecording = true
            committed = transcript

            task = recognizer.recognitionTask(with: req) { [weak self] result, err in
                Task { @MainActor in
                    guard let self else { return }
                    if let result {
                        let sep = self.committed.isEmpty ? "" : "\n"
                        self.transcript = self.committed + sep + result.bestTranscription.formattedString
                    }
                    if err != nil || (result?.isFinal ?? false) {
                        if self.isRecording { self.stop() }
                    }
                }
            }
        } catch {
            self.error = error.localizedDescription
            stop()
        }
    }

    func stop() {
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
