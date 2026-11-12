import type {components} from './schema';

type Report = components['schemas']['ReportRevision'];
export type ComparisonObservation = Report['input']['observations'][number];
export type ComparisonRow = {
  key: string; metric: string; unit: string; currency: string | null;
  period_start: string; period_end: string;
  left: ComparisonObservation | null; right: ComparisonObservation | null;
  delta: number | null; percent: number | null; reason: string | null;
};
export type ReportComparison = {rows: ComparisonRow[]; warnings: string[]};
const keyOf = (o: ComparisonObservation) => JSON.stringify([o.metric,o.unit,o.currency,o.period_start,o.period_end]);
function group(report: Report): Map<string, ComparisonObservation[]> {
  const result = new Map<string, ComparisonObservation[]>();
  for (const observation of report.input.observations) {
    const key = keyOf(observation);
    result.set(key, [...(result.get(key) ?? []), observation]);
  }
  return result;
}
/** Compare saved observations for identical contexts; never infer growth or fill gaps. */
export function compareReports(left: Report, right: Report): ReportComparison {
  if (left.input.instrument_id !== right.input.instrument_id || left.input.asset_type !== right.input.asset_type
      || left.input.data_origin !== right.input.data_origin) {
    throw new Error('Porównanie wymaga tego samego instrumentu, typu aktywa i pochodzenia danych.');
  }
  const warnings = ['Zmiany dotyczą zapisanych obserwacji w identycznych okresach. Nie są porównaniem rok do roku ani prognozą wyników.'];
  if (left.methodology_version !== right.methodology_version) warnings.push('Raporty stosują różne wersje metodologii.');
  if (left.input.as_of !== right.input.as_of) warnings.push('Raporty mają różne daty stanu danych (as_of).');
  const a = group(left), b = group(right);
  const rows = [...new Set([...a.keys(), ...b.keys()])].sort().map(key => {
    const aa = a.get(key) ?? [], bb = b.get(key) ?? [];
    const context = (aa[0] ?? bb[0])!;
    const row: ComparisonRow = {key,metric:context.metric,unit:context.unit,currency:context.currency,
      period_start:context.period_start,period_end:context.period_end,
      left:aa.length === 1 ? aa[0]! : null,right:bb.length === 1 ? bb[0]! : null,delta:null,percent:null,reason:null};
    if (aa.length > 1 || bb.length > 1) row.reason = 'Niejednoznaczne obserwacje: więcej niż jedna pozycja dla tego samego kontekstu.';
    else if (!row.left || !row.right) row.reason = 'Brak obserwacji w jednym z raportów.';
    else if (row.left.status !== 'available' || row.right.status !== 'available') row.reason = 'Brak dostępnej wartości w jednym z raportów.';
    else {
      const before = row.left.value, after = row.right.value;
      const delta = after - before;
      if (!Number.isFinite(before) || !Number.isFinite(after) || !Number.isFinite(delta)) row.reason = 'Różnica nie jest skończoną liczbą.';
      else {
        row.delta = Object.is(delta,-0) ? 0 : delta;
        if (before <= 0) row.reason = 'Zmiana procentowa niedostępna dla zerowej lub ujemnej wartości bazowej.';
        else {
          const percent = delta / before * 100;
          if (Number.isFinite(percent) && !(percent === 0 && delta !== 0)) row.percent = Object.is(percent,-0) ? 0 : percent;
          else row.reason = 'Zmiana procentowa nie jest reprezentowalna jako skończona liczba.';
        }
      }
    }
    return row;
  });
  return {rows,warnings};
}
