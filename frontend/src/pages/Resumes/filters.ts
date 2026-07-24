export interface ResumeListFilters {
  candidateName: string;
  positionId?: string;
  status?: string;
}

export const createEmptyResumeListFilters = (): ResumeListFilters => ({
  candidateName: '',
  positionId: undefined,
  status: undefined,
});

export const buildResumeListParams = (
  filters: ResumeListFilters,
  reviewerId?: string,
) => ({
  ...(filters.candidateName ? { candidate_name: filters.candidateName } : {}),
  ...(filters.positionId ? { position_id: filters.positionId } : {}),
  ...(filters.status ? { status: filters.status } : {}),
  ...(reviewerId ? { reviewer_id: reviewerId } : {}),
});

export const buildCurrentResumeListParams = (
  filtersRef: { readonly current: ResumeListFilters },
  reviewerId?: string,
) => buildResumeListParams(filtersRef.current, reviewerId);
