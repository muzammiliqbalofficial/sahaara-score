import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "./client";
import type {
  ScoredApplicant,
  ApplicantDetail,
  SummaryStats,
  DecisionCreate,
  DecisionRead,
} from "./types";

// ── Applicant list ──────────────────────────────────────────────────────

export interface ApplicantListParams {
  offset?: number;
  limit?: number;
  band?: string;
  confidence?: string;
  review_status?: string;
  sort_by?: string;
  sort_order?: string;
  search?: string;
}

function useApplicantList(params: ApplicantListParams) {
  return useQuery({
    queryKey: ["applicants", params],
    queryFn: () =>
      get<ScoredApplicant[]>("/review/applicants", {
        offset: String(params.offset ?? 0),
        limit: String(params.limit ?? 50),
        band: params.band,
        confidence: params.confidence,
        review_status: params.review_status,
        sort_by: params.sort_by,
        sort_order: params.sort_order,
        search: params.search,
      }),
  });
}

// ── Applicant detail ────────────────────────────────────────────────────

function useApplicantDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["applicant", id],
    queryFn: () => get<ApplicantDetail>(`/review/applicants/${id}`),
    enabled: !!id,
  });
}

// ── Summary ─────────────────────────────────────────────────────────────

function useSummary() {
  return useQuery({
    queryKey: ["summary"],
    queryFn: () => get<SummaryStats>("/review/summary"),
  });
}

// ── Decision submission ─────────────────────────────────────────────────

function useSubmitDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      assessmentId,
      payload,
    }: {
      assessmentId: string;
      payload: DecisionCreate;
    }) =>
      post<DecisionRead>(
        `/review/assessments/${assessmentId}/decisions`,
        payload,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["applicant"] });
      qc.invalidateQueries({ queryKey: ["applicants"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
    },
  });
}

export { useApplicantList, useApplicantDetail, useSummary, useSubmitDecision };
