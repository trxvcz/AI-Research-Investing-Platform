import {useEffect, useState} from 'react';
import type {Source, Snapshot} from './source-identity';
import {snapshotPath, validateSnapshotIdentity} from './source-identity';

const time = (value: string) => new Intl.DateTimeFormat('pl-PL', {dateStyle:'medium', timeStyle:'medium', timeZone:'UTC'}).format(new Date(value)) + ' UTC';
export function SourceArchive({source, instrumentId}: {source: Source; instrumentId: string}) {
  const identity = JSON.stringify([source, instrumentId]);
  return <Archive key={identity} source={source} instrumentId={instrumentId}/>;
}
function Archive({source, instrumentId}: {source: Source; instrumentId: string}) {
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setSnapshot(undefined); setError('');
    async function load() {
      try {
        const response = await fetch(snapshotPath(source.snapshot_id), {signal:abort.signal, cache:'no-store', headers:{Accept:'application/json'}});
        if (!response.ok) throw Error(response.status === 404 ? 'Nie znaleziono oryginalnego pliku w archiwum.' : response.status === 503 ? 'Archiwum jest teraz niedostępne.' : 'Nie udało się odczytać archiwum (' + response.status + ').');
        const verified = validateSnapshotIdentity(source, instrumentId, await response.json());
        if (!abort.signal.aborted) setSnapshot(verified);
      } catch (failure) {
        if (!abort.signal.aborted) setError(failure instanceof TypeError ? 'Brak połączenia z lokalnym archiwum.' : (failure as Error).message);
      }
    }
    void load();
    return () => abort.abort();
  }, [open, attempt, source, instrumentId]);
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Oryginalny plik i metadane archiwum</summary>
    {open && !snapshot && !error && <p role="status">Wczytywanie metadanych…</p>}
    {error && <div role="alert"><p>{error}</p><button onClick={() => setAttempt(value => value + 1)}>Spróbuj ponownie</button></div>}
    {snapshot && <>
      <dl>
        <dt>Snapshot</dt><dd>{snapshot.snapshot_id}</dd>
        <dt>Rozmiar</dt><dd>{new Intl.NumberFormat('pl-PL').format(snapshot.byte_length)} bajtów</dd>
        <dt>Typ danych</dt><dd>{snapshot.media_type}</dd>
        <dt>SHA256</dt><dd><code style={{overflowWrap:'anywhere'}}>{snapshot.sha256}</code></dd>
        <dt>Adres źródła</dt><dd style={{overflowWrap:'anywhere'}}>{snapshot.source_url ?? 'Nie podano'}</dd>
        <dt>Stan danych na</dt><dd>{time(snapshot.as_of)}</dd>
        <dt>Dostępne od</dt><dd>{snapshot.available_at === null ? 'Nie podano' : time(snapshot.available_at)}</dd>
        <dt>Pobrano</dt><dd>{time(snapshot.retrieved_at)}</dd>
        <dt>Zapisano w archiwum</dt><dd>{time(snapshot.created_at)}</dd>
      </dl>
      <a download href={snapshotPath(snapshot.snapshot_id) + '/content'}>Pobierz oryginalną odpowiedź (.bin)</a>
      <p className="hint">Pobierany plik zawiera oryginalne bajty. Hash metadanych odpowiada źródłu wskazanemu w raporcie.</p>
    </>}
  </details>;
}
