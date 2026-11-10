export const metricLabels: Record<string, string> = {
  revenue: 'Przychód', net_income: 'Wynik netto', net_margin: 'Marża netto', close: 'Cena zamknięcia',
  cash_and_equivalents: 'Gotówka i ekwiwalenty',
  long_term_debt_current: 'Dług długoterminowy — część bieżąca',
  long_term_debt_noncurrent: 'Dług długoterminowy — część niebieżąca',
  operating_cash_flow: 'Przepływy z działalności operacyjnej',
  capital_expenditures: 'Nakłady na rzeczowe aktywa trwałe',
  free_cash_flow: 'Wolne przepływy pieniężne',
};
const date = (value: string) => new Intl.DateTimeFormat('pl-PL', {dateStyle:'medium', timeZone:'UTC'}).format(new Date(value));
export function observationPeriod(start: string, end: string): string {
  return start === end ? 'Stan na ' + date(end) : date(start) + ' – ' + date(end);
}
