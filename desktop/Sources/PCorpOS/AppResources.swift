import Foundation

/// Resolves a bundled resource file. Checks the real app bundle's
/// Contents/Resources/ first — the standard, codesign-friendly location
/// build_app.sh copies real resource files into — falling back to SPM's
/// `Bundle.module` for `swift run` dev mode, which has no real
/// Contents/Resources/ to check (it uses its own adjacent-.bundle
/// convention instead). Needed because `Bundle.module`'s generated
/// accessor looks for that .bundle at `Bundle.main.bundleURL` + name,
/// which for a packaged .app resolves to the bundle's root directory —
/// and codesign rejects anything sitting there besides `Contents/`
/// ("unsealed contents present in the bundle root"), confirmed directly
/// while building the packaging script. Real resource files in
/// Contents/Resources/ sidesteps that conflict entirely, rather than
/// fighting SPM's resource-bundle placement.
enum AppResources {
    static func url(forResource name: String, withExtension ext: String) -> URL? {
        if let resourceURL = Bundle.main.resourceURL {
            let candidate = resourceURL.appendingPathComponent("\(name).\(ext)")
            if FileManager.default.fileExists(atPath: candidate.path) {
                return candidate
            }
        }
        return Bundle.module.url(forResource: name, withExtension: ext)
    }
}
