import Foundation

/// VENTURES (2026-09-23, Phase 1) -- mirrors backend/app/ventures_db.py's
/// own row shapes exactly, same flat-Decodable/explicit-snake_case-
/// CodingKeys convention as every other model in this app.
public let ventureStatusOptions = ["idea", "research", "validation", "build", "launch", "growth", "mature", "paused", "closed"]
public let ventureLevelOptions = ["low", "medium", "high"]
public let ventureConfidenceOptions = ["high", "medium", "low"]
public let checklistItemStatusOptions = ["pending", "done", "skipped"]
public let customerStatusOptions = ["active", "churned"]
public let revenueEventTypeOptions = ["charge", "refund"]
public let marketingContentTypeOptions = ["social_post", "launch_announcement", "ad_copy"]
public let automationSuggestionStatusOptions = ["new", "dismissed", "implemented"]

public struct Venture: Identifiable, Decodable {
    public let id: Int
    public let name: String
    public let description: String?
    public let status: String
    public let type: String?
    public let revenueModel: String?
    public let ownerTime: String?
    public let automationLevel: String?
    public let setupCost: Double?
    public let monthlyRevenue: Double
    public let riskLevel: String?
    public let confidence: String?
    public let scoreLabel: String?
    public let notes: String?
    public let createdAt: String
    public let conceptSummary: String?
    public let positioningCopy: String?
    public let operationsSop: String?

    enum CodingKeys: String, CodingKey {
        case id, name, description, status, type, confidence, notes
        case revenueModel = "revenue_model"
        case ownerTime = "owner_time"
        case automationLevel = "automation_level"
        case setupCost = "setup_cost"
        case monthlyRevenue = "monthly_revenue"
        case riskLevel = "risk_level"
        case scoreLabel = "score_label"
        case createdAt = "created_at"
        case conceptSummary = "concept_summary"
        case positioningCopy = "positioning_copy"
        case operationsSop = "operations_sop"
    }
}

/// The manual-create form's payload -- separate Encodable type from
/// `Venture` (Decodable, read-only client-side), same split as
/// TradeDraft/Trade.
public struct VentureDraft: Encodable {
    public var name: String
    public var description: String?
    public var status: String
    public var type: String?
    public var revenueModel: String?
    public var ownerTime: String?
    public var automationLevel: String?
    public var setupCost: Double?
    public var monthlyRevenue: Double
    public var riskLevel: String?
    public var confidence: String?
    public var notes: String?

    public init(
        name: String, description: String? = nil, status: String = "idea", type: String? = nil,
        revenueModel: String? = nil, ownerTime: String? = nil, automationLevel: String? = nil,
        setupCost: Double? = nil, monthlyRevenue: Double = 0, riskLevel: String? = nil,
        confidence: String? = nil, notes: String? = nil
    ) {
        self.name = name
        self.description = description
        self.status = status
        self.type = type
        self.revenueModel = revenueModel
        self.ownerTime = ownerTime
        self.automationLevel = automationLevel
        self.setupCost = setupCost
        self.monthlyRevenue = monthlyRevenue
        self.riskLevel = riskLevel
        self.confidence = confidence
        self.notes = notes
    }

    enum CodingKeys: String, CodingKey {
        case name, description, status, type, confidence, notes
        case revenueModel = "revenue_model"
        case ownerTime = "owner_time"
        case automationLevel = "automation_level"
        case setupCost = "setup_cost"
        case monthlyRevenue = "monthly_revenue"
        case riskLevel = "risk_level"
    }
}

public struct Opportunity: Identifiable, Decodable {
    public let id: Int
    public let name: String
    public let description: String
    public let revenueModel: String?
    public let setupCost: Double?
    public let automationPotential: String?
    public let ownerTimeRequired: String?
    public let confidence: String?
    public let risks: String?
    public let recommendedNextStep: String?
    public let source: String
    public let status: String
    public let promotedVentureId: Int?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, name, description, confidence, risks, source, status
        case revenueModel = "revenue_model"
        case setupCost = "setup_cost"
        case automationPotential = "automation_potential"
        case ownerTimeRequired = "owner_time_required"
        case recommendedNextStep = "recommended_next_step"
        case promotedVentureId = "promoted_venture_id"
        case createdAt = "created_at"
    }
}

public struct VenturesDashboard: Decodable {
    public let totalVentures: Int
    public let activeVentures: Int
    public let testingVentures: Int
    public let pausedVentures: Int
    public let closedVentures: Int
    public let totalMonthlyRevenue: Double
    public let totalRevenueLast30d: Double
    public let byStatus: [String: Int]
    public let ventures: [Venture]

    enum CodingKeys: String, CodingKey {
        case totalVentures = "total_ventures"
        case activeVentures = "active_ventures"
        case testingVentures = "testing_ventures"
        case pausedVentures = "paused_ventures"
        case closedVentures = "closed_ventures"
        case totalMonthlyRevenue = "total_monthly_revenue"
        case totalRevenueLast30d = "total_revenue_last_30d"
        case byStatus = "by_status"
        case ventures
    }
}

/// Phase 2 (2026-09-24) -- the Validation Engine keeps full history: every
/// "Run Validation" call inserts a new row, never overwrites the last one,
/// so Josh can look back at an earlier report without paying for a re-run.
public struct ValidationReport: Identifiable, Decodable {
    public let id: Int
    public let ventureId: Int
    public let evidence: String?
    public let assumptions: String?
    public let unknowns: String?
    public let risks: String?
    public let verdict: String?
    public let confidence: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, evidence, assumptions, unknowns, risks, verdict, confidence
        case ventureId = "venture_id"
        case createdAt = "created_at"
    }
}

/// Phase 2 (2026-09-24) -- seeded from Venture Builder's suggested SOP
/// steps (source == "builder") or added by hand (source == "manual"),
/// then freely editable either way. The Launch Engine's gate refuses to
/// launch while any item here is still "pending".
public struct ChecklistItem: Identifiable, Decodable {
    public let id: Int
    public let ventureId: Int
    public let title: String
    public let status: String
    public let position: Int
    public let source: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, title, status, position, source
        case ventureId = "venture_id"
        case createdAt = "created_at"
    }
}

/// Phase 3 (2026-09-24) -- a real customer of a venture. acquisitionCost
/// is Josh's own honest, optional estimate (nullable -- CAC is only ever
/// averaged over customers where this is actually recorded, never
/// assumed for the rest).
public struct Customer: Identifiable, Decodable {
    public let id: Int
    public let ventureId: Int
    public let name: String
    public let status: String
    public let acquisitionSource: String?
    public let acquisitionCost: Double?
    public let acquiredAt: String
    public let churnedAt: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, name, status
        case ventureId = "venture_id"
        case acquisitionSource = "acquisition_source"
        case acquisitionCost = "acquisition_cost"
        case acquiredAt = "acquired_at"
        case churnedAt = "churned_at"
        case createdAt = "created_at"
    }
}

/// Phase 3 (2026-09-24) -- an append-only ledger entry, never mutated in
/// place. A refund is its own new row, not an edit to the original charge.
public struct RevenueEvent: Identifiable, Decodable {
    public let id: Int
    public let customerId: Int
    public let amount: Double
    public let eventType: String
    public let occurredAt: String
    public let notes: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, amount, notes
        case customerId = "customer_id"
        case eventType = "event_type"
        case occurredAt = "occurred_at"
        case createdAt = "created_at"
    }
}

/// Phase 3 (2026-09-24) -- mirrors compute_customer_metrics' exact
/// output. churnRate/averageLtv/averageCac are all nil (not 0) when
/// there's nothing real to compute them from -- "no customers yet" is
/// not the same claim as "0% churn."
public struct CustomerMetrics: Decodable {
    public let activeCustomers: Int
    public let churnedCustomers: Int
    public let totalCustomers: Int
    public let churnRate: Double?
    public let totalRevenue: Double
    public let revenueLast30d: Double
    public let averageLtv: Double?
    public let averageCac: Double?
    public let customersWithRecordedCac: Int

    enum CodingKeys: String, CodingKey {
        case activeCustomers = "active_customers"
        case churnedCustomers = "churned_customers"
        case totalCustomers = "total_customers"
        case churnRate = "churn_rate"
        case totalRevenue = "total_revenue"
        case revenueLast30d = "revenue_last_30d"
        case averageLtv = "average_ltv"
        case averageCac = "average_cac"
        case customersWithRecordedCac = "customers_with_recorded_cac"
    }
}

/// Phase 3 (2026-09-24) -- same shape as ChecklistItem, scoped to a
/// customer instead of a venture (Fulfilment Engine). Kept as its own
/// type rather than genericized, since ChecklistItem is already shipped
/// and stable.
public struct FulfillmentItem: Identifiable, Decodable {
    public let id: Int
    public let customerId: Int
    public let title: String
    public let status: String
    public let position: Int
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, title, status, position
        case customerId = "customer_id"
        case createdAt = "created_at"
    }
}

/// Phase 3 (2026-09-24) -- one row from GET /ventures/delta, the "since
/// you last looked" feed. Mirrors audit_db.list_recent_calls' own shape.
public struct VentureDeltaEvent: Identifiable, Decodable {
    public let id: Int
    public let toolName: String
    public let result: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, result
        case toolName = "tool_name"
        case createdAt = "created_at"
    }
}

/// Phase 4 (2026-09-24) -- persisted history of past Marketing Content
/// generations, newest first. Kept (never overwritten) since Josh will
/// want to look back at prior drafts, unlike Operations/SOP which is a
/// single living document.
public struct MarketingContent: Identifiable, Decodable {
    public let id: Int
    public let ventureId: Int
    public let contentType: String
    public let content: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, content
        case ventureId = "venture_id"
        case contentType = "content_type"
        case createdAt = "created_at"
    }
}

/// Phase 4 (2026-09-24) -- one Automation Scout suggestion. Josh marks
/// each one implemented or dismissed individually, same review-card
/// pattern as Opportunity Radar's own opportunities.
public struct AutomationSuggestion: Identifiable, Decodable {
    public let id: Int
    public let ventureId: Int
    public let title: String
    public let description: String
    public let suggestedApproach: String?
    public let status: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, title, description, status
        case ventureId = "venture_id"
        case suggestedApproach = "suggested_approach"
        case createdAt = "created_at"
    }
}

/// Phase 4 (2026-09-24) -- minimal Decision Journal linkage: only rows
/// explicitly tagged with this venture at write time (today, just the
/// launch decision) -- most ventures will have none, an honest empty
/// state, not a gap.
public struct DecisionRecord: Identifiable, Decodable {
    public let id: Int
    public let decision: String
    public let reasoning: String?
    public let alternatives: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, decision, reasoning, alternatives
        case createdAt = "created_at"
    }
}
