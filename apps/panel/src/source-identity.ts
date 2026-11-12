import type {components} from './schema';

export type Source = components['schemas']['SourceProvenance'];
export type Snapshot = components['schemas']['SnapshotRecord'];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const timestamp = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
export function snapshotPath(snapshotId: string): string {
  if (!uuid.test(snapshotId)) throw Error('Identyfikator źródła nie wskazuje archiwalnego pliku.');
  return '/v1/snapshots/' + encodeURIComponent(snapshotId);
}
/** Bind server metadata to this report before exposing the original attachment. */
export function validateSnapshotIdentity(source: Source, instrumentId: string, metadata: unknown): Snapshot {
  snapshotPath(source.snapshot_id);
  if (!metadata || typeof metadata !== 'object') throw Error('Nieprawidłowe metadane archiwum.');
  const item = metadata as Partial<Snapshot>;
  if (item.snapshot_id !== source.snapshot_id || item.instrument_id !== instrumentId
      || item.source_id !== source.source_id || item.sha256 !== source.sha256
      || item.source_url !== source.url || item.license !== source.license
      || !timestamp(item.retrieved_at) || !timestamp(source.retrieved_at)
      || Date.parse(item.retrieved_at) !== Date.parse(source.retrieved_at)) {
    throw Error('Metadane archiwum nie odpowiadają źródłu tego raportu. Pobranie jest zablokowane.');
  }
  if (item.schema_version !== '1.0' || !/^[0-9a-f]{64}$/.test(item.sha256 ?? '')
      || !Number.isSafeInteger(item.byte_length) || item.byte_length! < 1 || item.byte_length! > 1048576
      || !['live','synthetic'].includes(item.data_origin ?? '')
      || !['application/json','text/plain','text/csv','application/pdf','application/octet-stream'].includes(item.media_type ?? '')
      || !timestamp(item.as_of) || !timestamp(item.created_at)
      || (item.available_at !== null && !timestamp(item.available_at))) {
    throw Error('Nieprawidłowe metadane archiwum. Pobranie jest zablokowane.');
  }
  return item as Snapshot;
}
