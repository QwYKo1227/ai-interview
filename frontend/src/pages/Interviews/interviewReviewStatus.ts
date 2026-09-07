export type InterviewReviewStatus = 'pending' | 'reviewed' | null;

export const getMyInterviewReviewStatus = (
  record: any,
  userId?: string,
): InterviewReviewStatus => {
  if (!userId || record?.lifecycle_state !== 'ended') return null;

  const memberIds = Array.isArray(record?.panel_members)
    ? record.panel_members.map((id: unknown) => String(id))
    : [];
  if (!memberIds.includes(String(userId))) return null;

  const panel = Array.isArray(record?.panels)
    ? record.panels.find((item: any) => String(item?.interviewer_id) === String(userId))
    : undefined;
  return panel?.human_review_submitted_at ? 'reviewed' : 'pending';
};
