// Type definitions matching the backend Pydantic schemas.

export type ConfidenceLevel = "high" | "medium" | "low";
export type ScoreBand = "strong" | "moderate" | "low";
export type DecisionOutcome = "approved" | "denied";
export type RiskLevel = "clean" | "low_risk" | "moderate_flag" | "high_suspicion" | "critical_mismatch";
export type AnomalySeverity = "info" | "warning" | "critical";
export type PolicyActionType = "auto_approve" | "standard_review" | "field_audit_required" | "high_risk_reject";

export interface FeatureContribution {
  feature: string;
  label?: string | null;
  contribution: number;
  direction: "positive" | "negative" | "neutral";
  explanation: string;
  raw_value?: number | null;
  no_data?: boolean;
}

export interface AnomalyFlagSchema {
  code: string;
  severity: AnomalySeverity;
  title: string;
  message: string;
  evidence: Record<string, unknown>;
}

export interface PolicyRecommendationSchema {
  action_type: PolicyActionType;
  recommended_support: string;
  summary_justification: string;
}

export interface AnomalyReportSchema {
  risk_score: number;
  risk_level: RiskLevel;
  audit_required: boolean;
  flags_count: number;
  flags: AnomalyFlagSchema[];
  top_flags: string[];
  recommendation: PolicyRecommendationSchema | null;
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
  anomaly_risk_score: number;
  anomaly_risk_level: RiskLevel;
  anomaly_audit_required: boolean;
  anomaly_flags_count: number;
  top_flags: string[];
  created_at: string;
}

export interface AssessmentWithExplanations extends AssessmentRead {
  feature_contributions: FeatureContribution[] | null;
  data_sufficiency_summary: string | null;
  categories_present: string[] | null;
  months_of_data: number | null;
  anomaly_report: AnomalyReportSchema | null;
  case_brief?: CaseBriefResponse | null;
}

export interface EnglishBriefSchema {
  key_strengths: string;
  vulnerability_profile: string;
  contradiction_analysis: string;
  directive: string;
}

export interface AwardPackageSchema {
  tier: string;
  conditions: string[];
  disbursement_schedule: string;
}

export interface CaseBriefResponse {
  english_brief: EnglishBriefSchema;
  urdu_brief: string;
  recommended_award_package: AwardPackageSchema;
  mode: string;
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
  // Anomaly summary (flattened from the assessment).
  anomaly_risk_score: number;
  anomaly_risk_level: RiskLevel;
  anomaly_audit_required: boolean;
  anomaly_flags_count: number;
  top_flags: string[];
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
