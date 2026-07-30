export const canRecordFullInterview = (
  panelMembers: unknown[],
  userId: unknown,
) => {
  const normalizedUserId = userId == null ? '' : String(userId);

  return panelMembers.length === 0
    || panelMembers.some((memberId) => String(memberId) === normalizedUserId);
};
