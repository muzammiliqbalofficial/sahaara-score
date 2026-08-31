// Type definitions matching the backend Pydantic schemas.

export type ConfidenceLevel = "high" | "medium" | "low";
export type ScoreBand = "strong" | "moderate" | "low";
export type DecisionOutcome = "approved" | "denied";

export interface FeatureContribution {
  feature: string;
  contribution: number;
  direction: "positive" | "negative" | "neutral";
  explanation: string;
  no_data?: boolean;
}

export interface AssessmentRead {
  id: string;
  applicant_id: string;
  score: number;
  band: ScoreBand;
  model_version: string;
  is_rule_based: boolean;
  confidence_level: ConfidenceLevel;
  signal_categories_count: number;
  non_null_feature_count: number;
  created_at: string;
}

export interface AssessmentWithExplanations extends AssessmentRead {
  feature_contributions: FeatureContribution[] | null;
  data_sufficiency_summary: string | null;
  categories_present: string[] | null;
  months_of_data: number | null;
}

export interface ScoredApplicant {
  id: string;
  identity_reference: string | null;
  applicant_type: string | null;
  city: string | null;
  district: string | null;
  created_at: string;
  latest_assessment: AssessmentRead | null;
  has_decision: boolean;
  latest_decision_outcome: string | null;
}

export interface ApplicantRead {
  id: string;
  identity_reference: string | null;
  applicant_type: string | null;
  city: string | null;
  district: string | null;
  created_at: string;
}

export interface UtilityRecordRead {
  id: string;
  applicant_id: string;
  utility_type: string | null;
  billing_month: string | null;
  amount_billed: number | null;
  amount_paid: number | null;
  days_late: number | null;
  created_at: string;
}

export interface AcademicRecordRead {
  id: string;
  applicant_id: string;
  institution: string | null;
  qualification_level: string | null;
  result_value: number | null;
  result_scale: string | null;
  year: number | null;
  created_at: string;
}

export interface IncomeSignalRead {
  id: string;
  applicant_id: string;
  source_type: string | null;
  declared_monthly_amount: number | null;
  evidence_type: string | null;
  confidence_flag: boolean | null;
  created_at: string;
}

export interface DecisionRead {
  id: string;
  assessment_id: string;
  reviewer: string | null;
  outcome: DecisionOutcome;
  rationale: string | null;
  created_at: string;
}

export interface ApplicantDetail {
  applicant: ApplicantRead;
  latest_assessment: AssessmentWithExplanations | null;
  utility_records: UtilityRecordRead[];
  academic_records: AcademicRecordRead[];
  income_signals: IncomeSignalRead[];
  decisions: DecisionRead[];
}

export interface DecisionCreate {
  reviewer?: string | null;
  outcome: DecisionOutcome;
  rationale?: string | null;
}

export interface BandCount {
  band: string;
  count: number;
}

export interface ConfidenceCount {
  confidence: string;
  count: number;
}

export interface CompletenessCount {
  categories: number;
  count: number;
}

export interface DecisionCount {
  outcome: string;
  count: number;
}

export interface ScoreBin {
  bin: string;
  count: number;
}

export interface SummaryStats {
  total_applicants: number;
  scored_applicants: number;
  mean_score: number | null;
  median_score: number | null;
  score_distribution: ScoreBin[];
  band_breakdown: BandCount[];
  confidence_breakdown: ConfidenceCount[];
  completeness_breakdown: CompletenessCount[];
  decision_counts: DecisionCount[];
  undecided_count: number;
}
