// Talks to scripts/dansk_app.py. Every request carries the per-run token the server put into
// index.html; without it the server answers 403.

const TOKEN =
  document.querySelector<HTMLMetaElement>('meta[name="dansk-token"]')?.content ?? '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: {
      'X-Dansk-Token': TOKEN,
      ...(body === undefined ? {} : {'Content-Type': 'application/json'}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  });
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const msg =
      data && typeof data === 'object' && 'error' in data
        ? String((data as {error: unknown}).error)
        : `request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export interface Learner {
  level?: string;
  target_level?: string;
  support_language?: string;
}

export interface PatternItem extends Record<string, unknown> {
  id: string;
  content: string | null;
  answer: string | null;
  category: string | null;
  due_date: string | null;
  total_reviews: number;
  mastery_level: number;
}

export interface SessionRow extends Record<string, unknown> {
  id: string;
  date: string;
  duration_minutes: number | null;
  size: string | null;
  input_mode: string | null;
  topic: string | null;
  skills: string[];
  accuracy: number | null;
  summary: string | null;
  errors: number;
  reviews: number;
  listening: number;
}

export interface Summary {
  today: string;
  example_data: boolean;
  demo: boolean;
  learner: Learner;
  due: number;
  words: number;
  grammar: number;
  items: number;
  sessions: number;
  reviews: number;
  streak: number;
  minutes_week: number;
  days: {date: string; minutes: number; reviews: number}[];
  patterns_due: PatternItem[];
  recent_sessions: SessionRow[];
}

export interface Card {
  item_id: string;
  kind: 'vocabulary' | 'grammar' | 'error_pattern';
  content: string | null;
  answer: string | null;
  category: string | null;
  due_date: string;
  mastery_level: number;
  total_reviews: number;
  word_id: number | null;
  headword: string | null;
  forms: string | null;
  definition: string | null;
  gloss: string | null;
  pos: string | null;
  gender: string | null;
  level: string | null;
  examples: string[];
  repetitions: number;
  interval_days: number;
  description: string | null;
  noted: string | null;
  context: string | null;
  severity?: string | null;
  mistake_date?: string | null;
  pairs?: [string, string][];
}

export interface ItemDetail {
  id: string;
  kind: string;
  content: string | null;
  answer: string | null;
  category: string | null;
  description: string | null;
  context: string | null;
  word_id: number | null;
}

export type ItemEdit = Partial<Record<'content' | 'answer' | 'description' | 'context' | 'category', string | null>>;

export type VoiceKind = 'local' | 'system' | 'none';

export interface PracticeSnapshot {
  id: string;
  mode: string;
  topic: string | null;
  state: 'starting' | 'replying' | 'waiting' | 'saved' | 'finished' | 'ended';
  saved_line: string | null;
  payload_file: string | null;
  events: number;
}

export interface PracticeStatus {
  available: boolean;
  problem: 'sdk' | 'key' | null;
  message: string;
  model: string;
  goal: string;
  topics: string[];
  modes: Record<string, string>;
  session: PracticeSnapshot | null;
}

export type PracticeEvent = {seq: number} & (
  | {type: 'text'; text: string}
  | {type: 'listen'; sentence: string}
  | {type: 'signal'; signal: 'your_turn' | 'listening' | 'replay' | 'saving' | 'done'; detail: string}
  | {type: 'turn_end'; text: string}
  | {type: 'user'; text: string; via: 'typed' | 'voice'}
  | {type: 'state'; state: PracticeSnapshot['state']}
  | {type: 'saved'; line: string; lines: string[]}
  | {type: 'save_error'; problems: string[]; path: string | null}
  | {type: 'fix'; said: string; correct: string; why: string}
  | {type: 'discard'}
  | {type: 'error'; message: string; kind?: string}
);

export interface PreviewOption {
  quality: number;
  label: string;
  easiness_factor: number;
  interval_days: number;
  repetitions: number;
  due_date: string;
}

export interface ReviewResult {
  item_id: string;
  quality: number;
  interval_days: number;
  due_date: string;
  session_id: string;
  due_left: number;
}

export interface WordRow extends Record<string, unknown> {
  id: number;
  headword: string;
  kind: 'word' | 'grammar';
  pos: string | null;
  gender: string | null;
  level: string | null;
  forms: string | null;
  gloss: string | null;
  learned: string | null;
  item_id: string | null;
  mastery_level: number | null;
  due_date: string | null;
  total_reviews: number | null;
  is_due: boolean;
}

export interface ReviewRow extends Record<string, unknown> {
  id: number;
  session_id: string | null;
  date: string;
  quality: number;
  ef_after: number | null;
  interval_after: number | null;
}

export interface WordDetail {
  id: number;
  headword: string;
  kind: 'word' | 'grammar';
  pos: string | null;
  gender: string | null;
  level: string | null;
  forms: string | null;
  definition: string | null;
  gloss: string | null;
  notes: string | null;
  learned: string | null;
  source: string | null;
  today: string;
  examples: {id: number; sentence: string; session_id: string | null}[];
  items: {
    id: string;
    kind: string;
    easiness_factor: number;
    interval_days: number;
    repetitions: number;
    due_date: string | null;
    last_reviewed: string | null;
    total_reviews: number;
    mastery_level: number;
    reviews: ReviewRow[];
  }[];
}

export type WordEdit = Partial<
  Record<'headword' | 'forms' | 'definition' | 'gloss' | 'pos' | 'gender' | 'level' | 'notes', string | null>
>;

export interface SessionErrorRow extends Record<string, unknown> {
  pattern_id: string;
  category: string | null;
  said: string | null;
  correct: string | null;
  context: string | null;
  severity: string | null;
}

export interface SessionFull {
  id: string;
  date: string;
  duration_minutes: number | null;
  size: string | null;
  input_mode: string | null;
  topic: string | null;
  skills: string[];
  accuracy: number | null;
  summary: string | null;
  errors: SessionErrorRow[];
  listening: {sentence: string; result: string}[];
  reviews: {item_id: string; quality: number; interval_after: number | null; content: string | null}[];
}

export const api = {
  summary: () => call<Summary>('GET', '/api/summary'),
  due: () => call<{today: string; cards: Card[]}>('GET', '/api/due'),
  preview: (itemId: string) =>
    call<{item_id: string; options: PreviewOption[]}>(
      'GET',
      `/api/review/preview?item_id=${encodeURIComponent(itemId)}`,
    ),
  review: (itemId: string, quality: number, elapsedSeconds: number) =>
    call<ReviewResult>('POST', '/api/review', {
      item_id: itemId,
      quality,
      elapsed_seconds: Math.max(0, Math.round(elapsedSeconds)),
    }),
  words: (f: {q?: string; kind?: string; level?: string; due?: string}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) {
      if (v) {
        p.set(k, v);
      }
    }
    return call<{today: string; words: WordRow[]; levels: string[]}>('GET', `/api/words?${p}`);
  },
  word: (id: number) => call<WordDetail>('GET', `/api/words/${id}`),
  editWord: (id: number, fields: WordEdit) => call<WordDetail>('PUT', `/api/words/${id}`, fields),
  deleteWord: (id: number) =>
    call<{deleted: Record<string, number>}>('DELETE', `/api/words/${id}`),
  sessions: () => call<{sessions: SessionRow[]}>('GET', '/api/sessions'),
  session: (id: string) => call<SessionFull>('GET', `/api/sessions/${encodeURIComponent(id)}`),
  item: (id: string) => call<ItemDetail>('GET', `/api/items/${encodeURIComponent(id)}`),
  editItem: (id: string, fields: ItemEdit) =>
    call<ItemDetail>('PUT', `/api/items/${encodeURIComponent(id)}`, fields),
  deleteItem: (id: string) =>
    call<{deleted: Record<string, number>}>('DELETE', `/api/items/${encodeURIComponent(id)}`),
  voice: () => call<{voice: VoiceKind; label: string; setting: string}>('GET', '/api/voice'),
  speak: (text: string, slow = false) => call<{voice: VoiceKind}>('POST', '/api/speak', {text, slow}),
  speakStop: () => call<{stopped: boolean}>('POST', '/api/speak/stop'),
  practice: () => call<PracticeStatus>('GET', '/api/practice'),
  practiceStart: (mode: string, topic?: string) =>
    call<PracticeSnapshot>('POST', '/api/practice/start', topic ? {mode, topic} : {mode}),
  practiceEvents: (id: string, after: number) =>
    call<{events: PracticeEvent[]; session: PracticeSnapshot}>('GET', `/api/practice/${id}/events?after=${after}`),
  practiceSend: (id: string, text: string, via: 'typed' | 'voice') =>
    call<PracticeSnapshot>('POST', `/api/practice/${id}/message`, {text, via}),
  practiceAction: (id: string, action: 'end' | 'retry' | 'stop') =>
    call<PracticeSnapshot>('POST', `/api/practice/${id}/${action}`),
};

// Stop a practice session while the page is being closed (keepalive lets the request finish).
export function stopPracticeOnUnload(id: string) {
  try {
    void fetch(`/api/practice/${id}/stop`, {method: 'POST', keepalive: true, headers: {'X-Dansk-Token': TOKEN}});
  } catch {
    // the server's watchdog stops it anyway once polling ends
  }
}

// Pages refetch when this fires: after a practice session saves, and when the window gets
// focus again.
export const DATA_CHANGED = 'dansk-data-changed';

export function announceDataChanged() {
  window.dispatchEvent(new Event(DATA_CHANGED));
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) {
    return 'not scheduled';
  }
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'});
}

export function daysLabel(n: number): string {
  return n === 1 ? '1 day' : `${n} days`;
}
