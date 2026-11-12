type ReportRun = {
  run_id: string;
  status: string;
  created_at: string | null;
  report_id: string | null;
  revision: number | null;
};

function newest<T extends ReportRun>(items: readonly T[]): T | undefined {
  return items.reduce<T | undefined>((selected, item) => {
    const timestamp = item.created_at === null ? NaN : Date.parse(item.created_at);
    const selectedTimestamp = selected?.created_at == null ? NaN : Date.parse(selected.created_at);
    if (!selected || (Number.isFinite(timestamp) && (!Number.isFinite(selectedTimestamp) || timestamp > selectedTimestamp))) return item;
    return selected;
  }, undefined);
}

export function selectReportRun<T extends ReportRun>(items: readonly T[], selectedId: string): T | undefined {
  const selected = items.find(item => item.run_id === selectedId);
  if (selected) return selected;
  const completed = items.filter(item => item.status === 'completed' && item.report_id !== null && item.revision !== null && item.revision >= 1);
  return newest(completed) ?? newest(items);
}
