"""
Domain enumerations used across models, schemas, and services.

Design decision: every enum inherits from ``str`` so that:
  - JSON serialisation is automatic (no custom encoders needed).
  - Postgres stores human-readable VARCHAR values, making direct SQL
    queries and debugging far easier than opaque integer codes.
"""

import enum


class ApplicantType(str, enum.Enum):
    """The primary eligibility category an applicant self-declares."""

    STUDENT = "student"
    FREELANCER = "freelancer"
    HOUSEHOLD = "household"


class UtilityType(str, enum.Enum):
    """Supported utility bill categories."""

    ELECTRICITY = "electricity"
    GAS = "gas"
    WATER = "water"


class QualificationLevel(str, enum.Enum):
    """
    Academic qualification tiers, ordered roughly by prestige.

    MATRIC and INTERMEDIATE use percentage scales.
    BACHELORS and MASTERS may use GPA or division scales.
    """

    MATRIC = "matric"
    INTERMEDIATE = "intermediate"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    DIPLOMA = "diploma"


class ResultScale(str, enum.Enum):
    """
    The measurement scale for an academic result value.

    Design note: Pakistani institutions use wildly different grading systems.
    We capture the raw value *and* its scale so the feature engineering layer
    can normalise them into a comparable 0-1 signal.

    - PERCENTAGE: 0-100 (common for matric / intermediate boards)
    - GPA: 0.0-4.0 (common for universities)
    - DIVISION: 1=First, 2=Second, 3=Third (older universities)
    """

    PERCENTAGE = "percentage"
    GPA = "gpa"
    DIVISION = "division"


class IncomeSourceType(str, enum.Enum):
    """How the applicant earns or receives money."""

    FREELANCE = "freelance"
    INFORMAL_WORK = "informal_work"
    REMITTANCE = "remittance"
    AGRICULTURE = "agriculture"


class EvidenceType(str, enum.Enum):
    """
    What kind of proof backs an income signal.

    Used by the scoring engine to weight confidence:
    VERIFIED > DOCUMENTED > SELF_DECLARED.
    """

    SELF_DECLARED = "self_declared"
    DOCUMENTED = "documented"
    VERIFIED = "verified"


class ScoreBand(str, enum.Enum):
    """
    Human-readable score classification shown to reviewers.

    Thresholds are defined in the scoring service, not here, so they can
    be tuned without a migration.
    """

    LOW = "low"
    MODERATE = "moderate"
    STRONG = "strong"


class DecisionOutcome(str, enum.Enum):
    """The final reviewer decision on an assessment."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    NEEDS_MORE_INFO = "needs_more_info"


class ConfidenceLevel(str, enum.Enum):
    """
    How much trust to place in a computed score.

    HIGH:   sufficient data across multiple signal categories.
    MEDIUM: some gaps, but core signals present.
    LOW:    thin file — score is indicative but not definitive.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
