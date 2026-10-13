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

public struct PostJob: Identifiable, Decodable, Equatable {
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
    public let highlightsGeneratedAt: String?

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
        case highlightsGeneratedAt = "highlights_generated_at"
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

/// Phase 9 (2026-09-28) -- mirrors detect_highlight_candidates' exact
/// output. The non-dialogue counterpart to SmartSelectCandidate: a real,
/// deterministic motion/audio-energy signal, never a claim about which
/// moment is creatively best. Stored (unlike smart selects, which are
/// derived fresh every request) since the real ffmpeg analysis behind
/// it is a genuine per-file background job, not a cheap re-derivation.
public struct HighlightCandidate: Decodable, Identifiable {
    public let start: Double
    public let duration: Double
    public let source: String   // "motion" | "audio" | "both"

    public var id: Double { start }

    enum CodingKeys: String, CodingKey {
        case start, duration, source
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

// MARK: - Edit planning (2026-10-09): style / song / opening clip

/// One saved reference edit a plan can take its style from (GET /post/jobs/{id}/edit-options).
public struct EditStyleOption: Decodable, Identifiable, Equatable {
    public let slug: String
    public let title: String
    public let description: String
    public let format: String
    public let seconds: Double?
    public let medianShotSeconds: Double?
    public let shots: Int?
    public let hasAccents: Bool
    /// "music_montage" or "narrated_broll" (nil from an older backend, which only knew music-driven styles).
    public let editType: String?

    public var id: String { slug }

    public var isNarratedStory: Bool { editType == "narrated_broll" }
    public var isDialogueLed: Bool { editType == "dialogue_led" }

    enum CodingKeys: String, CodingKey {
        case slug, title, description, format, seconds, shots
        case medianShotSeconds = "median_shot_seconds"
        case hasAccents = "has_accents"
        case editType = "edit_type"
    }
}

public struct EditMusicFile: Decodable, Identifiable, Equatable {
    public let path: String
    public let name: String
    public let megabytes: Double

    public var id: String { path }
}

public struct EditMusicOptions: Decodable, Equatable {
    public let folder: String
    public let files: [EditMusicFile]
    public let defaultPath: String?

    enum CodingKeys: String, CodingKey {
        case folder, files
        case defaultPath = "default"
    }
}

/// A clip the opening/closing slot can be filled with. `scene` is what the clip shows, when it has been probed.
public struct EditClipOption: Decodable, Identifiable, Equatable {
    public let fileId: Int
    public let name: String
    public let duration: Double
    public let scene: String
    public let people: Bool?
    public let hasMoments: Bool

    public var id: Int { fileId }

    enum CodingKeys: String, CodingKey {
        case name, duration, scene, people
        case fileId = "file_id"
        case hasMoments = "has_moments"
    }
}

public struct EditPlanChecks: Decodable, Equatable {
    public let shotCount: Int?
    public let shotLengthMedian: Double?
    public let styleMedian: Double?
    public let cutsOnHits: Double?
    public let distinctClips: Int?

    enum CodingKeys: String, CodingKey {
        case shotCount = "shot_count"
        case shotLengthMedian = "shot_length_median"
        case styleMedian = "style_median"
        case cutsOnHits = "cuts_on_hits"
        case distinctClips = "distinct_clips"
    }
}

public struct EditAccentCounts: Decodable, Equatable {
    public let flashes: Int
    public let zoomHits: Int
    public let shotZoomBlur: Int
    public let blackAndWhiteShots: Int
    public let logo: Int
    public let sfx: Int

    enum CodingKeys: String, CodingKey {
        case flashes, logo, sfx
        case zoomHits = "zoom_hits"
        case shotZoomBlur = "shot_zoom_blur"
        case blackAndWhiteShots = "black_and_white_shots"
    }
}

public struct EditPreviewInfo: Decodable, Equatable {
    public let path: String
    public let renderedAt: String
    /// False when the plan's moments or music changed after this preview was rendered.
    public let upToDate: Bool

    enum CodingKeys: String, CodingKey {
        case path
        case renderedAt = "rendered_at"
        case upToDate = "up_to_date"
    }
}

public struct EditOpeningClip: Decodable, Equatable {
    public let fileId: Int
    public let name: String

    enum CodingKeys: String, CodingKey {
        case name
        case fileId = "file_id"
    }
}

/// What the job's saved edit plan is, and how far along it is.
public struct EditSavedPlan: Decodable, Equatable {
    public let plannedAt: String
    public let style: String?
    public let shots: Int
    public let seconds: Double
    public let musicName: String
    public let musicInSeconds: Double?
    public let tempoBpm: Double?
    public let openingClip: EditOpeningClip?
    public let checks: EditPlanChecks
    public let notes: [String]
    public let reviewed: Int
    public let swapped: Int
    public let accents: EditAccentCounts?
    public let accentNotes: [String]
    public let preview: EditPreviewInfo?

    enum CodingKeys: String, CodingKey {
        case style, shots, seconds, checks, notes, reviewed, swapped, accents, preview
        case plannedAt = "planned_at"
        case musicName = "music_name"
        case musicInSeconds = "music_in_seconds"
        case tempoBpm = "tempo_bpm"
        case openingClip = "opening_clip"
        case accentNotes = "accent_notes"
    }
}

public struct EditMomentsCoverage: Decodable, Equatable {
    public let probed: Int
    public let total: Int
}

public struct EditOptions: Decodable, Equatable {
    public let styles: [EditStyleOption]
    public let music: EditMusicOptions
    public let clips: [EditClipOption]
    public let moments: EditMomentsCoverage
    public let logo: String?
    public let savedPlan: EditSavedPlan?
    /// What describing the undescribed clips would cost, and the state of a run (also fetched on its own while polling).
    public let describe: MomentsStatus?

    enum CodingKeys: String, CodingKey {
        case styles, music, clips, moments, logo, describe
        case savedPlan = "saved_plan"
    }
}

/// Body of POST /post/jobs/{id}/edit-plan. Nil fields are left out so the backend's own defaults apply.
public struct EditPlanRequestBody: Encodable {
    public var style: [String]
    public var musicPath: String?
    public var musicInSeconds: Double?
    public var targetSeconds: Double?
    public var bookendFileId: Int?
    /// Narration script for a narrated b-roll story (nil = cut at the style's own rhythm). An older backend ignores it.
    public var script: String?
    /// Talking head: the clips that filmed the same interview (two or more; the first is the reference) and which one's own audio is the dialogue.
    public var cameraFileIds: [Int]?
    public var audioFileId: Int?
    /// Corporate story: lay the job's logo over the b-roll as opening/closing brand cards and a corner logo bug, and burn the narration captions in (an older backend ignores these).
    public var brandGraphics: Bool?
    public var burnCaptions: Bool?
    public var cardTagline: String?
    public var cardContact: [String]?

    public init(style: [String], musicPath: String? = nil, musicInSeconds: Double? = nil, targetSeconds: Double? = nil, bookendFileId: Int? = nil, script: String? = nil,
                cameraFileIds: [Int]? = nil, audioFileId: Int? = nil, brandGraphics: Bool? = nil, burnCaptions: Bool? = nil, cardTagline: String? = nil, cardContact: [String]? = nil) {
        self.style = style
        self.musicPath = musicPath
        self.musicInSeconds = musicInSeconds
        self.targetSeconds = targetSeconds
        self.bookendFileId = bookendFileId
        self.script = script
        self.cameraFileIds = cameraFileIds
        self.audioFileId = audioFileId
        self.brandGraphics = brandGraphics
        self.burnCaptions = burnCaptions
        self.cardTagline = cardTagline
        self.cardContact = cardContact
    }

    enum CodingKeys: String, CodingKey {
        case style
        case musicPath = "music_path"
        case musicInSeconds = "music_in_seconds"
        case targetSeconds = "target_seconds"
        case bookendFileId = "bookend_file_id"
        case script
        case cameraFileIds = "camera_file_ids"
        case audioFileId = "audio_file_id"
        case brandGraphics = "brand_graphics"
        case burnCaptions = "burn_captions"
        case cardTagline = "card_tagline"
        case cardContact = "card_contact"
    }
}

// MARK: - Describing clips (2026-10-10): what each clip shows, found by Claude, costs real credits

/// What describing the remaining clips would cost AT MOST, from measured tokens per clip and an assumed price.
public struct MomentsEstimate: Decodable, Equatable {
    public let clips: Int
    public let inputTokens: Int
    public let outputTokens: Int
    public let usdAtMost: Double
    public let assumption: String

    enum CodingKeys: String, CodingKey {
        case clips, assumption
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case usdAtMost = "usd_at_most"
    }
}

public struct MomentsUsage: Decodable, Equatable {
    public let inputTokens: Int?
    public let outputTokens: Int?
    public let calls: Int?

    enum CodingKeys: String, CodingKey {
        case calls
        case inputTokens = "in"
        case outputTokens = "out"
    }
}

/// A describe-clips run in the backend: "running", "done", "stopped" (credits ran out), "cancelled" or "failed".
public struct MomentsRun: Decodable, Equatable {
    public let state: String
    public let total: Int
    public let done: Int
    public let failed: [String]
    public let startedAt: String
    public let finishedAt: String?
    public let message: String?
    public let usage: MomentsUsage?

    public var isRunning: Bool { state == "running" }

    enum CodingKeys: String, CodingKey {
        case state, total, done, failed, message, usage
        case startedAt = "started_at"
        case finishedAt = "finished_at"
    }
}

public struct MomentsStatus: Decodable, Equatable {
    public let total: Int
    public let described: Int
    public let missing: Int
    public let estimate: MomentsEstimate
    public let run: MomentsRun?
    public let apiKeySet: Bool

    enum CodingKeys: String, CodingKey {
        case total, described, missing, estimate, run
        case apiKeySet = "api_key_set"
    }
}
