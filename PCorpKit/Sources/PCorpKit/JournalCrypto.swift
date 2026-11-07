import CryptoKit
import Foundation

/// The private journal's encryption (2026-11-07). Everything in the journal is sealed on his iPhone or Mac before it goes anywhere, with one
/// key that only his devices hold, so the server, Frank and anyone reading the database see scrambled bytes. Each item is sealed with its own
/// name as authenticated data, so a sealed note can't be passed off as another one. Losing the key loses the journal: the recovery code is the
/// only other copy, and it's his to write down.
public enum JournalCrypto {
    public enum Failure: Error, Equatable {
        case damaged
        case wrongRecoveryCode
    }

    private static let format: UInt8 = 1
    private static let checkLabel = Data("p-corp-journal-key-check-v1".utf8)

    public static func newKey() -> SymmetricKey {
        SymmetricKey(size: .bits256)
    }

    /// A value the server keeps so a second device can tell its key is the right one. It can't be turned back into the key.
    public static func keyCheck(_ key: SymmetricKey) -> String {
        hex(Data(HMAC<SHA256>.authenticationCode(for: checkLabel, using: key)))
    }

    public static func seal(_ plain: Data, id: String, key: SymmetricKey) throws -> Data {
        let box = try ChaChaPoly.seal(plain, using: key, authenticating: Data(id.utf8))
        return Data([format]) + box.combined
    }

    public static func open(_ sealed: Data, id: String, key: SymmetricKey) throws -> Data {
        guard sealed.first == format else { throw Failure.damaged }
        do {
            let box = try ChaChaPoly.SealedBox(combined: sealed.dropFirst())
            return try ChaChaPoly.open(box, using: key, authenticating: Data(id.utf8))
        } catch {
            throw Failure.damaged
        }
    }

    public static func keyData(_ key: SymmetricKey) -> Data {
        key.withUnsafeBytes { Data($0) }
    }

    // ---- the recovery code: the key plus a two-byte check, in letters that can't be misread (no I, L, O or U), in groups of five

    private static let alphabet = Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    public static func recoveryCode(for key: SymmetricKey) -> String {
        let raw = keyData(key)
        let bytes = raw + Data(SHA256.hash(data: raw)).prefix(2)
        var bits = 0, value = 0
        var letters: [Character] = []
        for byte in bytes {
            value = (value << 8) | Int(byte)
            bits += 8
            while bits >= 5 {
                letters.append(alphabet[(value >> (bits - 5)) & 31])
                bits -= 5
            }
        }
        if bits > 0 { letters.append(alphabet[(value << (5 - bits)) & 31]) }
        return stride(from: 0, to: letters.count, by: 5).map { String(letters[$0..<min($0 + 5, letters.count)]) }.joined(separator: "-")
    }

    /// A recovery code, or part of one, as he typed or scanned it: spaces, dashes and case don't matter, and the letters people mix up are read as the digits they look like.
    public static func tidied(_ code: String) -> String {
        let mixups: [Character: Character] = ["O": "0", "I": "1", "L": "1"]
        return String(code.uppercased().compactMap { ch -> Character? in
            if ch.isWhitespace || ch == "-" { return nil }
            return mixups[ch] ?? ch
        })
    }

    /// The key from a recovery code as he typed or scanned it.
    public static func key(fromRecoveryCode code: String) throws -> SymmetricKey {
        let cleaned = tidied(code)
        var bits = 0, value = 0
        var bytes = Data()
        for ch in cleaned {
            guard let digit = alphabet.firstIndex(of: ch) else { throw Failure.wrongRecoveryCode }
            value = ((value << 5) | digit) & 0xFFFF
            bits += 5
            if bits >= 8 {
                bytes.append(UInt8((value >> (bits - 8)) & 0xFF))
                bits -= 8
            }
        }
        guard bytes.count == 34 else { throw Failure.wrongRecoveryCode }
        let raw = bytes.prefix(32)
        guard Data(SHA256.hash(data: raw)).prefix(2) == bytes.suffix(2) else { throw Failure.wrongRecoveryCode }
        return SymmetricKey(data: raw)
    }

    static func hex(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }
}
