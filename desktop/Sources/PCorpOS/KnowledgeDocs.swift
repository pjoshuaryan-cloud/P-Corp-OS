import Foundation

/// A doc in the "Knowledge" section — the project's own foundational
/// markdown files, browsable inside the app itself. Not a generic file
/// browser: Frank's own knowledge starts with the documents that define
/// him, and they're already real, already living, already local.
struct KnowledgeDoc: Identifiable {
    let id = UUID()
    let filename: String
    let title: String
    let subtitle: String
}

enum KnowledgeDocs {
    static let all: [KnowledgeDoc] = [
        KnowledgeDoc(filename: "FOUNDER_BRIEF.md", title: "Founder Brief", subtitle: "The authoritative source of truth"),
        KnowledgeDoc(filename: "ROADMAP.md", title: "Roadmap", subtitle: "Phased build sequence"),
        KnowledgeDoc(filename: "TECH_STACK.md", title: "Tech Stack", subtitle: "Platform decisions and trade-offs"),
        KnowledgeDoc(filename: "ARCHITECTURE.md", title: "Architecture", subtitle: "Three-layer system design"),
        KnowledgeDoc(filename: "PERSONALITY_SPEC.md", title: "Personality Spec", subtitle: "Frank's character model"),
        KnowledgeDoc(filename: "MEMORY_SYSTEM.md", title: "Memory System", subtitle: "How Frank remembers"),
        KnowledgeDoc(filename: "SECURITY.md", title: "Security", subtitle: "Permission model and threat model"),
        KnowledgeDoc(filename: "UI_GUIDELINES.md", title: "UI Guidelines", subtitle: "Visual language decisions"),
        KnowledgeDoc(filename: "ENGINEERING_MANUAL.md", title: "Engineering Manual", subtitle: "Code review, workflow, tooling"),
        KnowledgeDoc(filename: "WAR_ROOM.md", title: "War Room", subtitle: "The home screen concept"),
        KnowledgeDoc(filename: "ALPHA_MODE.md", title: "Alpha Mode", subtitle: "Business integration plan"),
        KnowledgeDoc(filename: "TRADING_DIVISION.md", title: "Trading Division", subtitle: "Frank's role with the robot"),
        KnowledgeDoc(filename: "MASTER_SPEC.md", title: "Master Spec", subtitle: "Top-level project spec"),
        KnowledgeDoc(filename: "README.md", title: "README", subtitle: "Repo overview"),
        KnowledgeDoc(filename: "CHANGELOG.md", title: "Changelog", subtitle: "Full build history"),
    ]

    static func content(for doc: KnowledgeDoc) -> String {
        let url = ProjectPaths.repoRoot.appendingPathComponent(doc.filename)
        return (try? String(contentsOf: url, encoding: .utf8)) ?? "Couldn't read \(doc.filename)."
    }
}
