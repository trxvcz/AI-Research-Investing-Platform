export const supportedSymbols = ['AAPL', 'GOOGL', 'GOOG'] as const;
export type Market = 'XNAS' | 'XNYS' | 'XWAR' | null;
export type Attempt = { symbol: string; run_id: string; exchange_mic?: Market };
export const marketLabel = (market: Market | undefined): string => market == null ? 'USA \u2014 automatycznie' : ({XNAS:'Nasdaq',XNYS:'NYSE',XWAR:'GPW'}[market]);
export const attemptIdentity = (item: Pick<Attempt,'symbol'|'exchange_mic'>) => item.symbol + ':' + (item.exchange_mic ?? 'AUTO');
export const attemptKey = 'alphasense.pending-analysis.v1';
export function normalizeSymbol(value: string): string { return value.trim().toUpperCase(); }
export function isSupported(value: string): boolean { return /^[A-Z][A-Z0-9.-]{0,15}$/.test(normalizeSymbol(value)); }
export function parseAttempt(raw: string | null): Attempt | undefined {
  if (!raw) return undefined;
  try {
    const item = JSON.parse(raw);
    if (typeof item.symbol === 'string' && isSupported(item.symbol) && item.symbol === normalizeSymbol(item.symbol)
      && typeof item.run_id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(item.run_id)) {
      if (item.exchange_mic !== undefined && item.exchange_mic !== null && !['XNAS','XNYS','XWAR'].includes(item.exchange_mic)) return undefined;
      return {symbol:item.symbol,run_id:item.run_id,...(item.exchange_mic !== undefined ? {exchange_mic:item.exchange_mic} : {})};
    }
  } catch { /* Untrusted or old session state is not a request. */ }
  return undefined;
}
export function selectAttempt(symbol: string, previous: Attempt | undefined, uuid: () => string, exchange_mic?: Market): Attempt {
  const normalized = normalizeSymbol(symbol);
  if (!isSupported(normalized)) throw new Error('Unsupported symbol');
  if (previous) {
    if (previous.symbol !== normalized || (previous.exchange_mic ?? null) !== (exchange_mic ?? null)) throw new Error('Resolve previous attempt first');
    return previous;
  }
  return {symbol: normalized, run_id: uuid(), ...(exchange_mic !== undefined ? {exchange_mic} : {})};
}

export const attemptHistoryKey = 'alphasense.parked-analyses.v1';
export function parseAttempts(raw: string | null): Attempt[] {
  try {
    const values: unknown = JSON.parse(raw ?? '[]');
    if (!Array.isArray(values)) return [];
    const valid = values.map(value => parseAttempt(JSON.stringify(value))).filter((item): item is Attempt => !!item);
    return valid.filter((item, index) => valid.findIndex(other => attemptIdentity(other) === attemptIdentity(item)) === index).slice(0, 50);
  } catch { return []; }
}
