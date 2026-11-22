import Foundation

// All JSON is snake_case on the server; API decodes with .convertFromSnakeCase.

struct OK: Decodable { let ok: Bool? }

struct ServerInfo: Decodable {
    let name: String
    let version: String
    let registrationOpen: Bool
    let ai: Bool
    let transcription: Bool
    let publicUrl: String?
}

struct AuthResponse: Decodable {
    let token: String
    let user: User
}

struct User: Decodable, Identifiable, Hashable {
    let id: Int
    let username: String
    let displayName: String
    let bio: String?
    let isPrivate: Bool
    let email: String?
    let isAdmin: Bool?
    let units: String?
}

struct RecipeSummary: Decodable, Identifiable, Hashable {
    let id: Int
    let title: String
    let imageUrl: String?
    let sourceDomain: String?
    let sourceType: String?
    let categories: [String]
    let cuisine: String?
    let totalTime: Int?
    let favorite: Bool
    let rating: Int?
    let owner: String?
    let createdAt: String?
    let lastCookedAt: String?
}

struct RenderedIngredient: Decodable, Hashable {
    let raw: String
    let quantity: Double?
    let quantityMax: Double?
    let unit: String?
    let size: String?
    let name: String
    let note: String?
    let group: String?
    let display: String
    let displayQuantity: String?
    let displayUnit: String?
}

struct RecipeStep: Codable, Hashable {
    var text: String
    var section: String?
}

struct Nutrition: Decodable, Hashable {
    let calories: Double?
    let proteinG: Double?
    let carbsG: Double?
    let fatG: Double?
    let saturatedFatG: Double?
    let fiberG: Double?
    let sugarG: Double?
    let sodiumMg: Double?
    let assumedServings: Double?
    let source: String?
}

struct RecipeComponent: Decodable, Hashable {
    let name: String
    let ingredients: [String]
    let steps: [String]
    let feedsInto: String?
}

struct RecipeDetail: Decodable, Identifiable, Hashable {
    let id: Int
    let title: String
    let imageUrl: String?
    let sourceDomain: String?
    let sourceType: String?
    let categories: [String]
    let cuisine: String?
    let totalTime: Int?
    let favorite: Bool
    let rating: Int?
    let owner: String?
    let description: String?
    let sourceUrl: String?
    let author: String?
    let servings: Double?
    let servingsText: String?
    let currentServings: Double?
    let scale: Double
    let units: String
    let prepTime: Int?
    let cookTime: Int?
    let ingredients: [RenderedIngredient]
    let steps: [RecipeStep]
    let nutrition: Nutrition?
    let components: [RecipeComponent]?
    let notes: String?
    let isPublic: Bool
    let isOwner: Bool
    let shareUrl: String?
    let collectionIds: [Int]
}

struct ImportResponse: Decodable {
    let saved: Bool
    let duplicate: Bool?
    let recipe: RecipeDetail?
}

struct CategoryCount: Decodable, Identifiable, Hashable {
    var id: String { name }
    let name: String
    let count: Int
    let imageUrl: String?
}

struct RecipeCollection: Decodable, Identifiable, Hashable {
    let id: Int
    let name: String
    let icon: String?
    let count: Int
    let imageUrl: String?
}

struct ShoppingItem: Decodable, Identifiable, Hashable {
    let id: Int
    let name: String
    let quantity: Double?
    let unit: String?
    let aisle: String
    let checked: Bool
    let sources: [String]
    let display: String
}

struct ShoppingAisle: Decodable, Hashable {
    let aisle: String
    let items: [ShoppingItem]
}

struct ShoppingList: Decodable {
    let aisles: [ShoppingAisle]
    let checked: [ShoppingItem]
    let count: Int
}

struct JournalEntry: Decodable, Identifiable, Hashable {
    let id: Int
    let user: User?
    let recipe: RecipeSummary?
    let text: String?
    let rating: Int?
    let photoUrl: String?
    let isPublic: Bool
    let cookedAt: String?
}

struct FeedItem: Decodable, Identifiable, Hashable {
    var id: String { "\(type)-\(entry?.id ?? recipe?.id ?? 0)-\(at)" }
    let type: String  // "cooked" | "saved"
    let at: String
    let entry: JournalEntry?
    let recipe: RecipeSummary?
    let user: User?
}

struct Feed: Decodable { let items: [FeedItem] }

struct UserListItem: Decodable, Identifiable, Hashable {
    let id: Int
    let username: String
    let displayName: String
    let bio: String?
    let isPrivate: Bool
    let following: Bool
}

struct Profile: Decodable {
    let id: Int
    let username: String
    let displayName: String
    let bio: String?
    let isPrivate: Bool
    let following: Bool
    let followers: Int
    let followingCount: Int
    let recipeCount: Int
    let recipes: [RecipeSummary]
    let journal: [JournalEntry]
    let hidden: Bool
}

struct FollowState: Decodable { let following: Bool }
struct MediaUpload: Decodable { let url: String }
struct BackupResult: Decodable { let imported: Int }

// MARK: - Request bodies

struct IngredientInput: Encodable { var raw: String; var group: String? }

struct RecipeInput: Encodable {
    var title: String
    var description: String?
    var imageUrl: String?
    var sourceUrl: String?
    var author: String?
    var servings: Double?
    var servingsText: String?
    var prepTime: Int?
    var cookTime: Int?
    var totalTime: Int?
    var ingredients: [IngredientInput]
    var steps: [RecipeStep]
    var categories: [String]?
    var cuisine: String?
    var notes: String?
    var rating: Int?
    var favorite: Bool
    var isPublic: Bool
}

// MARK: - Helpers

extension Date {
    static func fromISO(_ s: String?) -> Date? {
        guard let s else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s)
    }
}

func formatMinutes(_ m: Int?) -> String? {
    guard let m, m > 0 else { return nil }
    if m < 60 { return "\(m) min" }
    let h = m / 60, r = m % 60
    return r == 0 ? "\(h) h" : "\(h) h \(r) min"
}

func formatNumber(_ d: Double) -> String {
    d == d.rounded() ? String(Int(d)) : String(format: "%.1f", d)
}
