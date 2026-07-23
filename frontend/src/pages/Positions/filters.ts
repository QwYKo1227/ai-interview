export interface PositionListFilters {
  title: string;
  status?: string;
  hiringManagerId?: string;
}

export const buildPositionListParams = ({
  title,
  status,
  hiringManagerId,
}: PositionListFilters) => ({
  title,
  status,
  ...(hiringManagerId ? { hiring_manager_id: hiringManagerId } : {}),
});
