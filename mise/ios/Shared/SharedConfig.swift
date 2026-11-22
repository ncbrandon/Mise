import Foundation
import Security

/// Settings shared between the app and the share extension (App Group + Keychain).
enum SharedConfig {
    static var appGroup: String {
        Bundle.main.object(forInfoDictionaryKey: "MiseAppGroup") as? String ?? "group.com.example.mise"
    }

    static var defaults: UserDefaults { UserDefaults(suiteName: appGroup) ?? .standard }

    static var serverURL: URL? {
        get { defaults.string(forKey: "serverURL").flatMap(URL.init(string:)) }
        set { defaults.set(newValue?.absoluteString, forKey: "serverURL") }
    }

    static var token: String? {
        get { Keychain.read() }
        set {
            if let newValue { Keychain.save(newValue) } else { Keychain.delete() }
        }
    }

    /// Normalizes what people type: "192.168.1.5:8000" -> "http://192.168.1.5:8000"
    static func normalizeServer(_ raw: String) -> URL? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        guard !s.isEmpty else { return nil }
        if !s.lowercased().hasPrefix("http://") && !s.lowercased().hasPrefix("https://") {
            s = "http://" + s
        }
        return URL(string: s)
    }
}

/// Token storage. Uses the App Group as keychain access group so the share extension can read it;
/// falls back to the app's own keychain when the entitlement is missing (e.g. unsigned simulator builds).
enum Keychain {
    private static let service = "mise.token"

    private static func query(shared: Bool) -> [String: Any] {
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "token",
        ]
        if shared, let prefix = teamPrefix {
            q[kSecAttrAccessGroup as String] = prefix + SharedConfig.appGroup
        }
        return q
    }

    /// "ABCDE12345." — read from the app's own default keychain access group.
    private static var teamPrefix: String? = {
        let probe: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "mise.probe",
            kSecAttrAccount as String: "probe",
            kSecReturnAttributes as String: true,
        ]
        var result: AnyObject?
        var status = SecItemCopyMatching(probe as CFDictionary, &result)
        if status == errSecItemNotFound {
            var add = probe
            add[kSecValueData as String] = Data("1".utf8)
            status = SecItemAdd(add as CFDictionary, &result)
        }
        guard status == errSecSuccess, let attrs = result as? [String: Any],
              let group = attrs[kSecAttrAccessGroup as String] as? String,
              let dot = group.firstIndex(of: ".") else { return nil }
        return String(group[...dot])
    }()

    static func save(_ value: String) {
        delete()
        for shared in [true, false] {
            var q = query(shared: shared)
            q[kSecValueData as String] = Data(value.utf8)
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
            if SecItemAdd(q as CFDictionary, nil) == errSecSuccess { return }
        }
    }

    static func read() -> String? {
        for shared in [true, false] {
            var q = query(shared: shared)
            q[kSecReturnData as String] = true
            q[kSecMatchLimit as String] = kSecMatchLimitOne
            var out: AnyObject?
            if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
               let data = out as? Data, let s = String(data: data, encoding: .utf8) {
                return s
            }
        }
        return nil
    }

    static func delete() {
        SecItemDelete(query(shared: true) as CFDictionary)
        SecItemDelete(query(shared: false) as CFDictionary)
    }
}
