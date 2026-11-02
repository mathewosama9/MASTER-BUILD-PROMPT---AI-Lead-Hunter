from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


ROLE_RANK = {Role.VIEWER: 0, Role.ANALYST: 1, Role.ADMIN: 2, Role.OWNER: 3}


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    DISCOVERING = "discovering"
    ENRICHING = "enriching"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {
    CampaignStatus.QUEUED,
    CampaignStatus.DISCOVERING,
    CampaignStatus.ENRICHING,
    CampaignStatus.ANALYZING,
}
TERMINAL_STATUSES = {
    CampaignStatus.COMPLETED,
    CampaignStatus.PARTIALLY_COMPLETED,
    CampaignStatus.FAILED,
    CampaignStatus.CANCELLED,
}


class Stage(StrEnum):
    CREATED = "created"
    DISCOVERY = "discovery"
    NORMALIZATION = "normalization"
    DEDUPLICATION = "deduplication"
    COMPANY_ENRICHMENT = "company_enrichment"
    CONTACT_ENRICHMENT = "contact_enrichment"
    AI_ANALYSIS = "ai_analysis"
    LEAD_SCORING = "lead_scoring"
    PERSIST = "persist"
    NOTIFY = "notify"
    DONE = "done"


class ContactType(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    CONTACT_PAGE = "contact_page"
    SOCIAL = "social"
    PERSON = "person"


class VerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    INVALID = "invalid"
    RESTRICTED = "restricted"


class CrmStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    QUALIFIED = "qualified"
    READY_FOR_OUTREACH = "ready_for_outreach"
    CONTACTED = "contacted"
    REPLIED = "replied"
    MEETING_SCHEDULED = "meeting_scheduled"
    WON = "won"
    LOST = "lost"
    DO_NOT_CONTACT = "do_not_contact"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEEDS_REVIEW = "needs_review"


class ProviderStatus(StrEnum):
    CONNECTED = "connected"
    REQUIRES_API_KEY = "requires_api_key"
    REQUIRES_PERMISSION = "requires_permission"
    UNSUPPORTED = "unsupported"
    DISABLED = "disabled"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class SuppressionKind(StrEnum):
    DOMAIN = "domain"
    EMAIL = "email"
    PHONE = "phone"
    BUSINESS = "business"


class TelegramLinkStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"


class CreditKind(StrEnum):
    TRIAL_GRANT = "trial_grant"
    PURCHASE = "purchase"
    MANUAL_ADJUST = "manual_adjust"
    CAMPAIGN_CHARGE = "campaign_charge"
    REFUND = "refund"


class TopUpStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContactInterest(StrEnum):
    DEMO = "demo"
    SALES = "sales"
    SUPPORT = "support"
    PARTNERSHIP = "partnership"
    # Kept for requests stored before the rebrand; the site no longer offers them.
    LEAD_HUNTER = "lead_hunter"
    WHATSAPP_BOT = "whatsapp_bot"
    BOOKING = "booking"
    WEBSITE = "website"
    CRM = "crm"
    OTHER = "other"


class PaymentMethod(StrEnum):
    INSTAPAY = "instapay"
    BANK_TRANSFER = "bank_transfer"
    VODAFONE_CASH = "vodafone_cash"
    PAYPAL = "paypal"


class TestimonialSource(StrEnum):
    IN_APP = "in_app"
    MANUAL = "manual"
    SAMPLE = "sample"


class TestimonialStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    HIDDEN = "hidden"
