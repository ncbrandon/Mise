import SwiftUI

struct FriendsView: View {
    @State private var feed: [FeedItem] = []
    @State private var query = ""
    @State private var results: [UserListItem] = []
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if !query.isEmpty {
                    Section("People") {
                        if results.isEmpty { Text("No one found").foregroundStyle(.secondary) }
                        ForEach(results) { u in
                            NavigationLink(value: UserRef(username: u.username)) {
                                VStack(alignment: .leading) {
                                    Text(u.displayName).font(.headline)
                                    Text("@\(u.username)\(u.following ? " · following" : "")").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                } else {
                    if let error { Text(error).foregroundStyle(.red) }
                    if feed.isEmpty {
                        ContentUnavailableView("No activity yet", systemImage: "person.2",
                                               description: Text("Search for people on your server and follow them to see what they're cooking."))
                    }
                    ForEach(feed) { item in
                        if item.type == "cooked", let e = item.entry {
                            JournalRow(entry: e, showUser: true)
                        } else if let r = item.recipe {
                            HStack(spacing: 12) {
                                RemoteImage(url: r.imageUrl).frame(width: 64, height: 64).clipShape(RoundedRectangle(cornerRadius: 8))
                                VStack(alignment: .leading, spacing: 3) {
                                    if let u = item.user {
                                        NavigationLink(value: UserRef(username: u.username)) {
                                            Text("\(u.displayName) saved").font(.caption).foregroundStyle(.secondary)
                                        }
                                        .buttonStyle(.plain)
                                    }
                                    NavigationLink(value: RecipeRef(id: r.id)) { Text(r.title).font(.headline) }
                                        .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                }
            }
            .listStyle(.plain)
            .navigationTitle("Friends")
            .searchable(text: $query, prompt: "Find people")
            .task(id: query) {
                if query.isEmpty { await loadFeed() } else {
                    try? await Task.sleep(for: .milliseconds(250))
                    results = (try? await API.shared.searchUsers(query)) ?? []
                }
            }
            .refreshable { await loadFeed() }
            .navigationDestination(for: UserRef.self) { ProfileView(username: $0.username) }
            .navigationDestination(for: RecipeRef.self) { RecipeDetailView(recipeId: $0.id) }
        }
    }

    private func loadFeed() async {
        do { feed = try await API.shared.feed().items; error = nil } catch is CancellationError {} catch {
            self.error = error.localizedDescription
        }
    }
}

struct ProfileView: View {
    let username: String
    @Environment(AppState.self) private var app
    @State private var profile: Profile?
    @State private var error: String?

    var body: some View {
        ScrollView {
            if let p = profile {
                VStack(alignment: .leading, spacing: 12) {
                    Text(p.displayName).font(.system(.largeTitle, design: .serif).bold())
                    Text("@\(p.username)").foregroundStyle(.secondary)
                    if let bio = p.bio, !bio.isEmpty { Text(bio) }
                    HStack(spacing: 18) {
                        Text("**\(p.recipeCount)** recipes")
                        Text("**\(p.followers)** followers")
                        Text("**\(p.followingCount)** following")
                    }
                    .font(.subheadline)
                    if p.id != app.user?.id {
                        Button(p.following ? "Following" : "Follow") {
                            Task {
                                _ = try? await API.shared.follow(p.username, !p.following)
                                await load()
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(p.following ? .gray : .accentColor)
                    }
                    if p.hidden {
                        Label("This account is private.", systemImage: "lock").foregroundStyle(.secondary).padding(.top)
                    }
                }
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
                if !p.recipes.isEmpty {
                    Text("Recipes").font(.title3.bold()).padding(.horizontal)
                    RecipeGrid(recipes: p.recipes)
                }
                if !p.journal.isEmpty {
                    Text("Recently cooked").font(.title3.bold()).padding(.horizontal)
                    VStack { ForEach(p.journal) { JournalRow(entry: $0).padding(.horizontal) } }
                }
            } else if let error {
                ContentUnavailableView("Couldn't load profile", systemImage: "person.crop.circle.badge.exclamationmark", description: Text(error))
            } else {
                ProgressView().padding(.top, 60)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        do { profile = try await API.shared.profile(username) } catch { self.error = error.localizedDescription }
    }
}
