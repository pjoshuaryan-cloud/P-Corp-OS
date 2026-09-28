import Foundation

/// POST (2026-09-25, Phase 1) -- video post-production prep: drive
/// detection, footage ingestion with checksum verification, crash-safe
/// resumability. Flat Decodable/Encodable structs with explicit
/// snake_case CodingKeys, same convention as every other model in this
/// app -- mirrors backend/app/post_db.py's own row shapes exactly.
public let postProfileNames = ["joshx", "alpha_mode"]

/// Phase 3 (2026-09-25) -- the spec's own NEW SHOOT flow always asked
/// for these three; Phase 1 never captured them. Mirrors
/// backend/app/post_db.py's DELIVERABLE_FORMATS/RESOLUTIONS/FRAME_RATES
/// exactly.
public let postDeliverableFormatOptions = ["16:9", "9:16", "1:1", "4:5", "custom"]
public let postResolutionOptions = ["4k_uhd", "4k_dci", "custom"]
public let postFrameRateOptions = ["23.976", "24", "25", "29.97", "30", "50", "59.94", "other"]

public struct PostProfile: Decodable {
    public let label: String
    public let folders: [String]
}

public struct PostJob: Identifiable, Decodable {
    public let id: Int
    public let profile: String
    public let shootName: String
    public let clientName: String?
    public let sourcePath: String
    public let sourceVolumeName: String?
    public let sourceVolumeUuid: String?
    public let destinationRoot: String
    public let joshxProjectId: Int?
    public let alphaModeProjectId: Int?
    public let status: String
    public let totalFiles: Int
    public let totalBytes: Int
    public let filesCopied: Int
    public let filesFailed: Int
    public let bytesCopied: Int
    public let currentFilePath: String?
    public let errorMessage: String?
    public let startedAt: String?
    public let completedAt: String?
    public let createdAt: String
    public let estimatedRemainingSeconds: Double?
    public let mediaAnalyzedAt: String?
    public let deliverableFormat: String?
    public let resolution: String?
    public let frameRate: String?
    public let premiereProjectPath: String?
    public let proxiesGeneratedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, profile, status, resolution
        case shootName = "shoot_name"
        case clientName = "client_name"
        case sourcePath = "source_path"
        case sourceVolumeName = "source_volume_name"
        case sourceVolumeUuid = "source_volume_uuid"
        case destinationRoot = "destination_root"
        case joshxProjectId = "joshx_project_id"
        case alphaModeProjectId = "alpha_mode_project_id"
        case totalFiles = "total_files"
        case totalBytes = "total_bytes"
        case filesCopied = "files_copied"
        case filesFailed = "files_failed"
        case bytesCopied = "bytes_copied"
        case currentFilePath = "current_file_path"
        case errorMessage = "error_message"
        case startedAt = "started_at"
        case completedAt = "completed_at"
        case createdAt = "created_at"
        case estimatedRemainingSeconds = "estimated_remaining_seconds"
        case mediaAnalyzedAt = "media_analyzed_at"
        case deliverableFormat = "deliverable_format"
        case frameRate = "frame_rate"
        case premiereProjectPath = "premiere_project_path"
        case proxiesGeneratedAt = "proxies_generated_at"
    }

    /// true while the background loop could plausibly be actively
    /// working this job -- the UI's own signal for whether to keep
    /// polling and show a progress bar vs. a final state.
    public var isActive: Bool {
        ["scanning", "ready", "ingesting", "verifying", "analyzing_media", "generating_proxies"].contains(status)
    }
}

/// The NEW SHOOT form's payload -- separate Encodable type from PostJob
/// (Decodable, read-only client-side), same split as VentureDraft/Venture.
public struct PostJobDraft: Encodable {
    public var profile: String
    public var shootName: String
    public var sourcePath: String
    public var destinationVolumePath: String
    public var clientName: String?
    public var sourceVolumeName: String?
    public var sourceVolumeUuid: String?
    public var joshxProjectId: Int?
    public var alphaModeProjectId: Int?
    public var deliverableFormat: String?
    public var resolution: String?
    public var frameRate: String?

    public init(
        profile: String, shootName: String, sourcePath: String, destinationVolumePath: String,
        clientName: String? = nil, sourceVolumeName: String? = nil, sourceVolumeUuid: String? = nil,
        joshxProjectId: Int? = nil, alphaModeProjectId: Int? = nil,
        deliverableFormat: String? = nil, resolution: String? = nil, frameRate: String? = nil
    ) {
        self.profile = profile
        self.shootName = shootName
        self.sourcePath = sourcePath
        self.destinationVolumePath = destinationVolumePath
        self.clientName = clientName
        self.sourceVolumeName = sourceVolumeName
        self.sourceVolumeUuid = sourceVolumeUuid
        self.joshxProjectId = joshxProjectId
        self.alphaModeProjectId = alphaModeProjectId
        self.deliverableFormat = deliverableFormat
        self.resolution = resolution
        self.frameRate = frameRate
    }

    enum CodingKeys: String, CodingKey {
        case profile, resolution
        case shootName = "shoot_name"
        case sourcePath = "source_path"
        case destinationVolumePath = "destination_volume_path"
        case clientName = "client_name"
        case sourceVolumeName = "source_volume_name"
        case sourceVolumeUuid = "source_volume_uuid"
        case joshxProjectId = "joshx_project_id"
        case alphaModeProjectId = "alpha_mode_project_id"
        case deliverableFormat = "deliverable_format"
        case frameRate = "frame_rate"
    }
}

public struct SourceVolume: Identifiable, Decodable {
    public let name: String
    public let path: String
    public let uuid: String?
    public let filesystem: String?
    public let totalBytes: Int?
    public let freeBytes: Int?
    public let writable: Bool

    public var id: String { path }

    enum CodingKeys: String, CodingKey {
        case name, path, uuid, filesystem, writable
        case totalBytes = "total_bytes"
        case freeBytes = "free_bytes"
    }
}

public struct PostJobFile: Identifiable, Decodable {
    public let id: Int
    public let jobId: Int
    public let relativePath: String
    public let destinationPath: String
    public let sizeBytes: Int
    public let status: String
    public let bytesCopied: Int
    public let sourceChecksum: String?
    public let destinationChecksum: String?
    public let verifiedAt: String?
    public let errorMessage: String?
    public let attemptCount: Int
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, status
        case jobId = "job_id"
        case relativePath = "relative_path"
        case destinationPath = "destination_path"
        case sizeBytes = "size_bytes"
        case bytesCopied = "bytes_copied"
        case sourceChecksum = "source_checksum"
        case destinationChecksum = "destination_checksum"
        case verifiedAt = "verified_at"
        case errorMessage = "error_message"
        case attemptCount = "attempt_count"
        case createdAt = "created_at"
    }
}

/// Phase 2 (2026-09-25) -- mirrors compute_media_report's exact output.
/// A pure computed report, not a stored entity -- no `id`, refetched
/// fresh on every request.
public struct MediaReport: Decodable {
    public struct CameraCount: Decodable, Identifiable {
        public let make: String?
        public let model: String?
        public let count: Int
        public var id: String { "\(make ?? "")-\(model ?? "")" }
    }
    public struct ResolutionCount: Decodable, Identifiable {
        public let width: Int
        public let height: Int
        public let count: Int
        public var id: String { "\(width)x\(height)" }
    }
    public struct FrameRateCount: Decodable, Identifiable {
        public let fps: Double
        public let count: Int
        public var id: Double { fps }
    }
    public struct FlaggedFile: Decodable, Identifiable {
        public let path: String
        public let frameRate: Double?
        public let error: String?
        public var id: String { path }

        enum CodingKeys: String, CodingKey {
            case path, error
            case frameRate = "frame_rate"
        }
    }
    /// Phase 5 -- a file flagged for exposure or color-cast, distinct
    /// from FlaggedFile since the flag is a category label ("warm",
    /// "underexposed"), never a frame rate -- kept as its own small
    /// struct rather than overloading FlaggedFile's frameRate field
    /// with an unrelated meaning.
    public struct ColorFlagFile: Decodable, Identifiable {
        public let path: String
        public let flag: String
        public var id: String { path }
    }

    public let totalFiles: Int
    public let mediaTypeCounts: [String: Int]
    public let cameras: [CameraCount]
    public let deviceCategories: [String: Int]
    public let resolutions: [ResolutionCount]
    public let frameRates: [FrameRateCount]
    public let verticalCount: Int
    public let horizontalCount: Int
    public let slowMotionFiles: [FlaggedFile]
    public let corruptFiles: [FlaggedFile]
    public let duplicateGroups: [[String]]
    /// Phase 5 (2026-09-26) -- color intelligence: real color_transfer/
    /// color_primaries-based HDR detection, a best-effort Log-gamma
    /// guess from camera strings, and ffmpeg signalstats-based exposure/
    /// color-cast flags. All explicitly labeled as computed/best-effort
    /// in the UI, never asserted as color-managed measurements.
    public let colorProfileCounts: [String: Int]
    public let mixedColorSpaces: Bool
    public let flaggedExposureFiles: [ColorFlagFile]
    public let flaggedColorCastFiles: [ColorFlagFile]
    /// Phase 6 (2026-09-27) -- dialogue transcription, done entirely by
    /// Premiere's own native on-device engine (never this app's own STT
    /// integration). This just counts what's already been stored.
    public let dialogueSummary: DialogueSummary

    public struct DialogueSummary: Decodable {
        public let filesWithTranscripts: Int
        public let filesFlaggedProfanity: Int
        public let filesFlaggedFillerWords: Int
        public let filesPendingTranscription: Int

        enum CodingKeys: String, CodingKey {
            case filesWithTranscripts = "files_with_transcripts"
            case filesFlaggedProfanity = "files_flagged_profanity"
            case filesFlaggedFillerWords = "files_flagged_filler_words"
            case filesPendingTranscription = "files_pending_transcription"
        }
    }

    enum CodingKeys: String, CodingKey {
        case cameras, resolutions
        case totalFiles = "total_files"
        case mediaTypeCounts = "media_type_counts"
        case deviceCategories = "device_categories"
        case frameRates = "frame_rates"
        case verticalCount = "vertical_count"
        case horizontalCount = "horizontal_count"
        case slowMotionFiles = "slow_motion_files"
        case corruptFiles = "corrupt_files"
        case colorProfileCounts = "color_profile_counts"
        case mixedColorSpaces = "mixed_color_spaces"
        case flaggedExposureFiles = "flagged_exposure_files"
        case flaggedColorCastFiles = "flagged_color_cast_files"
        case duplicateGroups = "duplicate_groups"
        case dialogueSummary = "dialogue_summary"
    }
}

/// Phase 6 -- a stored transcript's own metadata + real content, fetched
/// on demand (GET /post/jobs/{id}/files/{file_id}/transcript), never
/// preloaded into the whole MediaReport. `readableText` is a plain,
/// speaker-grouped rendering of Premiere's own real transcript, never a
/// word-by-word timeline UI.
public struct Transcript: Decodable {
    public let id: Int
    public let fileId: Int
    public let language: String?
    public let wordCount: Int?
    public let speakerCount: Int?
    public let hasProfanity: Bool
    public let hasFillerWords: Bool
    public let srtPath: String?
    public let createdAt: String
    public let readableText: String

    enum CodingKeys: String, CodingKey {
        case id, language
        case fileId = "file_id"
        case wordCount = "word_count"
        case speakerCount = "speaker_count"
        case hasProfanity = "has_profanity"
        case hasFillerWords = "has_filler_words"
        case srtPath = "srt_path"
        case createdAt = "created_at"
        case readableText = "readable_text"
    }
}

/// Phase 4 (2026-09-26) -- mirrors compute_proxy_recommendations' exact
/// output. A pure computed suggestion, not a stored entity -- no `id`
/// of its own beyond the underlying file_id, refetched fresh on every
/// request.
public struct ProxyRecommendation: Decodable, Identifiable {
    public let fileId: Int
    public let relativePath: String
    public let width: Int?
    public let height: Int?
    public let bitRate: Int?
    public let videoCodec: String?
    public var id: Int { fileId }

    enum CodingKeys: String, CodingKey {
        case width, height
        case fileId = "file_id"
        case relativePath = "relative_path"
        case bitRate = "bit_rate"
        case videoCodec = "video_codec"
    }
}

/// Phase 4 -- mirrors post_job_file_proxies' own row shape, joined
/// against post_job_files for relative_path/destination_path.
public struct ProxyStatus: Decodable, Identifiable {
    public let id: Int
    public let fileId: Int
    public let status: String
    public let proxyPath: String?
    public let errorMessage: String?
    public let createdAt: String
    public let completedAt: String?
    public let relativePath: String
    public let destinationPath: String

    enum CodingKeys: String, CodingKey {
        case id, status
        case fileId = "file_id"
        case proxyPath = "proxy_path"
        case errorMessage = "error_message"
        case createdAt = "created_at"
        case completedAt = "completed_at"
        case relativePath = "relative_path"
        case destinationPath = "destination_path"
    }
}

/// Phase 8a (2026-09-27) -- mirrors find_smart_select_candidates' exact
/// output. A pure computed suggestion derived from an already-stored
/// real transcript, not a stored entity of its own -- refetched fresh
/// on every request, no `id`.
public struct SmartSelectCandidate: Decodable, Identifiable {
    public let start: Double
    public let duration: Double
    public let text: String
    public let confidence: Double?
    public let wordCount: Int

    public var id: Double { start }

    enum CodingKeys: String, CodingKey {
        case start, duration, text, confidence
        case wordCount = "word_count"
    }
}

/// Phase 8b (2026-09-27) -- a real, stored Claude vision judgment on
/// sampled frames from one file. Fetched on demand, never preloaded.
public struct VisualAnalysis: Decodable {
    public let id: Int
    public let fileId: Int
    public let analysisText: String
    public let frameCount: Int
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case fileId = "file_id"
        case analysisText = "analysis_text"
        case frameCount = "frame_count"
        case createdAt = "created_at"
    }
}
