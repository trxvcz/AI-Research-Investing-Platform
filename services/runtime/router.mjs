// A selection primitive, not an invoker or a shared quota ledger. Admission evidence
// must come from trusted operator configuration, never from a research document.
const timestampPattern = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?([Zz]|([+-])(\d{2}):(\d{2}))$/;

function timestamp(value) {
  if (typeof value !== 'string') return NaN;
  const match = timestampPattern.exec(value);
  if (!match) return NaN;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText,
    fraction = '', zone, sign, offsetHourText, offsetMinuteText] = match;
  const [year, month, day, hour, minute, second] =
    [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
  const offsetHour = Number(offsetHourText || 0);
  const offsetMinute = Number(offsetMinuteText || 0);
  if (year < 1 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 ||
      second > 59 || offsetHour > 23 || offsetMinute > 59) return NaN;
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, Number(fraction.padEnd(3, '0')));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 ||
      date.getUTCDate() !== day) return NaN;
  const offset = (offsetHour * 60 + offsetMinute) * 60000;
  return date.getTime() - (/^[Zz]$/.test(zone) ? 0 : sign === '+' ? offset : -offset);
}

function hasTerms(value) {
  if (typeof value !== 'string' || !/^https:\/\//i.test(value) || /\s|[\x00-\x1f\x7f]/u.test(value)) {
    return false;
  }
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password;
  } catch {
    return false;
  }
}

function eligible(candidate, now) {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return false;
  const id = candidate.id;
  const verifiedAt = timestamp(candidate.verified_at);
  const verifiedUntil = timestamp(candidate.verified_until);
  return typeof id === 'string' && id.length > 0 && id.length <= 128 && id === id.trim() &&
    !/[\x00-\x1f\x7f]/u.test(id) && candidate.enabled === true &&
    candidate.quality_pass === true && candidate.total_cost === 0 &&
    candidate.free_only_verified === true && candidate.paid_fallback === false &&
    Number.isSafeInteger(candidate.quota_remaining) && candidate.quota_remaining > 0 &&
    Number.isFinite(verifiedAt) && Number.isFinite(verifiedUntil) &&
    verifiedAt <= now && now < verifiedUntil && hasTerms(candidate.terms_reference);
}

export function choose(candidates, budget, {now = Date.now()} = {}) {
  if (!Array.isArray(candidates) || !Number.isFinite(budget) || budget < 0 ||
      !Number.isSafeInteger(now)) {
    throw Error('Invalid routing parameters');
  }
  const admitted = candidates.filter(candidate => eligible(candidate, now));
  if (!admitted.length) throw Error('No qualified free-only option');
  return admitted.sort((a, b) => a.id.localeCompare(b.id))[0];
}

