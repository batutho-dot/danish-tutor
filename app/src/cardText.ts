// Same rule as the server's dansk_db.error_pairs: split on " / " only when both sides give
// the same number of parts.
export function splitPairs(said: string | null, correct: string | null): [string, string][] {
  const a = (said ?? '').trim();
  const b = (correct ?? '').trim();
  const x = a.split(' / ');
  const y = b.split(' / ');
  if (x.length > 1 && x.length === y.length) {
    return x.map((s, i) => [s.trim(), y[i].trim()]);
  }
  return [[a, b]];
}
