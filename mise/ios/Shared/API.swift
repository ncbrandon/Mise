import Foundation

struct APIError: LocalizedError {
    let message: String
    var status: Int = 0
    var errorDescription: String? { message }
}

extension Notification.Name {
    static let miseUnauthorized = Notification.Name("miseUnauthorized")
}

struct UploadFile {
    let field: String
    let filename: String
    let mime: String
    let data: Data
}

final class API: @unchecked Sendable {
    static let shared = API()

    var baseURL: URL? { SharedConfig.serverURL }
    var token: String? { SharedConfig.token }

    private let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 240   // video imports + AI can take a while
        c.timeoutIntervalForResource = 600
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    // MARK: - Core

    func url(_ path: String, query: [String: String?] = [:], base: URL? = nil) throws -> URL {
        guard let root = base ?? baseURL else { throw APIError(message: "Set your server address first") }
        guard var comps = URLComponents(url: root, resolvingAgainstBaseURL: false) else {
            throw APIError(message: "Invalid server address")
        }
        let basePath = comps.path.hasSuffix("/") ? String(comps.path.dropLast()) : comps.path
        comps.path = basePath + path
        let items = query.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }
        if !items.isEmpty { comps.queryItems = items }
        guard let u = comps.url else { throw APIError(message: "Invalid URL") }
        return u
    }

    func send<T: Decodable>(_ method: String, _ path: String, query: [String: String?] = [:],
                            body: (any Encodable)? = nil, base: URL? = nil) async throws -> T {
        var req = URLRequest(url: try url(path, query: query, base: base))
        req.httpMethod = method
        if let body {
            req.httpBody = try Self.encoder.encode(body)
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return try await perform(req)
    }

    func upload<T: Decodable>(_ path: String, files: [UploadFile]) async throws -> T {
        let boundary = "mise-\(UUID().uuidString)"
        var req = URLRequest(url: try url(path))
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        for f in files {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(f.field)\"; filename=\"\(f.filename)\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: \(f.mime)\r\n\r\n".data(using: .utf8)!)
            body.append(f.data)
            body.append("\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body
        return try await perform(req)
    }

    func download(_ path: String) async throws -> Data {
        var req = URLRequest(url: try url(path))
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw Self.error(from: data, code: code) }
        return data
    }

    private func perform<T: Decodable>(_ request: URLRequest) async throws -> T {
        var req = request
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let result: (Data, URLResponse)
        do {
            result = try await session.data(for: req)
        } catch let e as URLError {
            throw APIError(message: e.code == .timedOut ? "The server took too long to answer."
                                                        : "Can't reach your server (\(e.localizedDescription))")
        }
        let (data, resp) = result
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            if code == 401, token != nil, !(req.url?.path.hasSuffix("/auth/login") ?? false) {
                NotificationCenter.default.post(name: .miseUnauthorized, object: nil)
            }
            throw Self.error(from: data, code: code)
        }
        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw APIError(message: "Unexpected answer from the server. Is the app up to date? (\(error))", status: code)
        }
    }

    private static func error(from data: Data, code: Int) -> APIError {
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let s = obj["detail"] as? String { return APIError(message: s, status: code) }
            if let arr = obj["detail"] as? [[String: Any]], let first = arr.first {
                let field = (first["loc"] as? [Any])?.last.map { "\($0)" } ?? ""
                let msg = first["msg"] as? String ?? "Invalid input"
                return APIError(message: field.isEmpty ? msg : "\(field): \(msg)", status: code)
            }
        }
        return APIError(message: "Server error (\(code))", status: code)
    }
}

// MARK: - Endpoints

extension API {
    // Account
    func serverInfo(at base: URL? = nil) async throws -> ServerInfo { try await send("GET", "/api/server", base: base) }
    func login(username: String, password: String) async throws -> AuthResponse {
        try await send("POST", "/api/auth/login", body: ["username": username, "password": password])
    }
    func register(username: String, password: String, displayName: String?) async throws -> AuthResponse {
        try await send("POST", "/api/auth/register",
                       body: ["username": username, "password": password, "display_name": displayName ?? username])
    }
    func me() async throws -> User { try await send("GET", "/api/me") }
    func updateMe(_ fields: [String: AnyEncodable]) async throws -> User { try await send("PATCH", "/api/me", body: fields) }

    // Recipes
    func recipes(query: String? = nil, category: String? = nil, collectionId: Int? = nil,
                 favorite: Bool? = nil, sort: String = "recent") async throws -> [RecipeSummary] {
        try await send("GET", "/api/recipes", query: [
            "q": query?.isEmpty == true ? nil : query,
            "category": category,
            "collection_id": collectionId.map(String.init),
            "favorite": favorite.map { $0 ? "true" : "false" },
            "sort": sort,
        ])
    }
    func categories() async throws -> [CategoryCount] { try await send("GET", "/api/recipes/categories") }
    func recipe(_ id: Int, servings: Double? = nil, scale: Double? = nil, units: String? = nil) async throws -> RecipeDetail {
        try await send("GET", "/api/recipes/\(id)", query: [
            "servings": servings.map { String($0) }, "scale": scale.map { String($0) }, "units": units,
        ])
    }
    func sharedRecipe(token: String, servings: Double? = nil, scale: Double? = nil, units: String? = nil) async throws -> RecipeDetail {
        try await send("GET", "/api/recipes/shared/\(token)", query: [
            "servings": servings.map { String($0) }, "scale": scale.map { String($0) }, "units": units,
        ])
    }
    func createRecipe(_ r: RecipeInput) async throws -> RecipeDetail { try await send("POST", "/api/recipes", body: r) }
    func updateRecipe(_ id: Int, _ r: RecipeInput) async throws -> RecipeDetail { try await send("PUT", "/api/recipes/\(id)", body: r) }
    func patchRecipe(_ id: Int, _ fields: [String: AnyEncodable]) async throws -> RecipeDetail {
        try await send("PATCH", "/api/recipes/\(id)", body: fields)
    }
    func deleteRecipe(_ id: Int) async throws { let _: OK = try await send("DELETE", "/api/recipes/\(id)") }
    func copyRecipe(_ id: Int, share: String? = nil) async throws -> RecipeDetail {
        try await send("POST", "/api/recipes/\(id)/copy", query: ["share": share])
    }
    func nutrition(_ id: Int) async throws -> RecipeDetail { try await send("POST", "/api/recipes/\(id)/nutrition") }
    func breakdown(_ id: Int) async throws -> RecipeDetail { try await send("POST", "/api/recipes/\(id)/breakdown") }
    func recategorize(_ id: Int) async throws -> RecipeDetail { try await send("POST", "/api/recipes/\(id)/recategorize") }
    func setImage(_ id: Int, jpeg: Data) async throws -> RecipeDetail {
        try await upload("/api/recipes/\(id)/image", files: [UploadFile(field: "file", filename: "photo.jpg", mime: "image/jpeg", data: jpeg)])
    }

    // Import
    func importURL(_ url: String) async throws -> ImportResponse {
        try await send("POST", "/api/import/url", body: ["url": url])
    }
    func importText(_ text: String, title: String? = nil, voice: Bool = false) async throws -> ImportResponse {
        var body: [String: String] = ["text": text, "source_type": voice ? "voice" : "text"]
        if let title, !title.isEmpty { body["title"] = title }
        return try await send("POST", "/api/import/text", body: body)
    }
    func importPhotos(_ jpegs: [Data]) async throws -> ImportResponse {
        try await upload("/api/import/photos", files: jpegs.enumerated().map {
            UploadFile(field: "files", filename: "page\($0.offset + 1).jpg", mime: "image/jpeg", data: $0.element)
        })
    }
    func importDocument(_ data: Data, filename: String, mime: String) async throws -> ImportResponse {
        try await upload("/api/import/document", files: [UploadFile(field: "file", filename: filename, mime: mime, data: data)])
    }
    func importBackup(_ data: Data) async throws -> BackupResult {
        try await upload("/api/import/backup", files: [UploadFile(field: "file", filename: "mise-export.json", mime: "application/json", data: data)])
    }

    // Collections
    func collections() async throws -> [RecipeCollection] { try await send("GET", "/api/collections") }
    func createCollection(_ name: String) async throws -> RecipeCollection { try await send("POST", "/api/collections", body: ["name": name]) }
    func renameCollection(_ id: Int, _ name: String) async throws -> RecipeCollection { try await send("PATCH", "/api/collections/\(id)", body: ["name": name]) }
    func deleteCollection(_ id: Int) async throws { let _: OK = try await send("DELETE", "/api/collections/\(id)") }
    func addToCollection(_ cid: Int, recipe: Int) async throws -> RecipeCollection { try await send("POST", "/api/collections/\(cid)/recipes/\(recipe)") }
    func removeFromCollection(_ cid: Int, recipe: Int) async throws -> RecipeCollection { try await send("DELETE", "/api/collections/\(cid)/recipes/\(recipe)") }

    // Shopping
    func shopping(units: String? = nil) async throws -> ShoppingList { try await send("GET", "/api/shopping", query: ["units": units]) }
    func addRecipeToShopping(_ id: Int, servings: Double?, indexes: [Int]?) async throws -> ShoppingList {
        var body: [String: AnyEncodable] = ["recipe_id": AnyEncodable(id)]
        if let servings { body["servings"] = AnyEncodable(servings) }
        if let indexes { body["ingredient_indexes"] = AnyEncodable(indexes) }
        return try await send("POST", "/api/shopping/recipe", body: body)
    }
    func addShoppingItem(_ text: String) async throws -> ShoppingList { try await send("POST", "/api/shopping/items", body: ["text": text]) }
    func setShoppingChecked(_ id: Int, _ checked: Bool) async throws -> ShoppingList {
        try await send("PATCH", "/api/shopping/items/\(id)", body: ["checked": checked])
    }
    func deleteShoppingItem(_ id: Int) async throws -> ShoppingList { try await send("DELETE", "/api/shopping/items/\(id)") }
    func clearCheckedShopping() async throws -> ShoppingList { try await send("POST", "/api/shopping/clear-checked") }
    func clearShopping() async throws -> ShoppingList { try await send("DELETE", "/api/shopping") }

    // Journal & social
    func journal(recipeId: Int? = nil) async throws -> [JournalEntry] {
        try await send("GET", "/api/journal", query: ["recipe_id": recipeId.map(String.init)])
    }
    func addJournal(recipeId: Int?, text: String?, rating: Int?, photoUrl: String?, isPublic: Bool) async throws -> JournalEntry {
        var body: [String: AnyEncodable] = ["is_public": AnyEncodable(isPublic)]
        if let recipeId { body["recipe_id"] = AnyEncodable(recipeId) }
        if let text, !text.isEmpty { body["text"] = AnyEncodable(text) }
        if let rating, rating > 0 { body["rating"] = AnyEncodable(rating) }
        if let photoUrl { body["photo_url"] = AnyEncodable(photoUrl) }
        return try await send("POST", "/api/journal", body: body)
    }
    func deleteJournal(_ id: Int) async throws { let _: OK = try await send("DELETE", "/api/journal/\(id)") }
    func uploadMedia(jpeg: Data) async throws -> String {
        let r: MediaUpload = try await upload("/api/media", files: [UploadFile(field: "file", filename: "photo.jpg", mime: "image/jpeg", data: jpeg)])
        return r.url
    }
    func searchUsers(_ q: String) async throws -> [UserListItem] { try await send("GET", "/api/users", query: ["q": q]) }
    func profile(_ username: String) async throws -> Profile { try await send("GET", "/api/users/\(username)") }
    func follow(_ username: String, _ on: Bool) async throws -> FollowState {
        try await send(on ? "POST" : "DELETE", "/api/users/\(username)/follow")
    }
    func feed() async throws -> Feed { try await send("GET", "/api/feed") }
}

/// Type-erased Encodable for mixed JSON bodies.
struct AnyEncodable: Encodable {
    private let encodeFn: (Encoder) throws -> Void
    init<T: Encodable>(_ value: T) { encodeFn = value.encode }
    func encode(to encoder: Encoder) throws { try encodeFn(encoder) }
}
