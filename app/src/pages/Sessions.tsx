// Scaffolded from the Astryx `table-page` template (Searchable Table frame: masthead, then a
// sortable Table, LayoutContent padding 0 with the padding on the VStack). Content replaced;
// a Drawer shows one session. #/sessions/<id> opens that session directly.

import {useEffect, useMemo, useState} from 'react';
import {HStack, Layout, LayoutContent, StackItem, VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {Badge} from '@astryxdesign/core/Badge';
import {Banner} from '@astryxdesign/core/Banner';
import {Drawer, DrawerHeader} from '@astryxdesign/core/Drawer';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Link} from '@astryxdesign/core/Link';
import {MetadataList, MetadataListItem} from '@astryxdesign/core/MetadataList';
import {Spinner} from '@astryxdesign/core/Spinner';
import {Table, pixel, proportional, useTableSortable, useTableSortableState} from '@astryxdesign/core/Table';
import type {TableColumn, TableSortComparator} from '@astryxdesign/core/Table';
import {api, daysLabel, fmtDate} from '../api';
import type {SessionErrorRow, SessionFull, SessionRow} from '../api';

const SEVERITY: Record<string, 'error' | 'warning' | 'neutral'> = {critical: 'error', moderate: 'warning', minor: 'neutral'};
const RESULT: Record<string, {label: string; variant: 'success' | 'warning' | 'error'}> = {
  understood_fully: {label: 'Understood', variant: 'success'},
  gist_only: {label: 'Gist only', variant: 'warning'},
  missed: {label: 'Missed', variant: 'error'},
};
const QUALITY_NAME: Record<number, string> = {0: 'Blackout', 1: 'Again', 2: 'Wrong', 3: 'Hard', 4: 'Good', 5: 'Easy'};

function idFromHash(): string | null {
  const m = window.location.hash.match(/^#\/sessions\/(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

const errorColumns: TableColumn<SessionErrorRow>[] = [
  {key: 'said', header: 'Said', width: proportional(1), renderCell: e => <Text hasStrikethrough color="secondary">{e.said ?? ''}</Text>},
  {key: 'correct', header: 'Correct', width: proportional(1), renderCell: e => <Text weight="medium">{e.correct ?? ''}</Text>},
  {key: 'category', header: 'Category', width: pixel(100), renderCell: e => <Text color="secondary">{e.category ?? ''}</Text>},
  {
    key: 'severity',
    header: 'Severity',
    width: pixel(100),
    renderCell: e => <Badge label={e.severity ?? 'moderate'} variant={SEVERITY[e.severity ?? 'moderate'] ?? 'neutral'} />,
  },
];

function SessionDrawer({id, onClose}: {id: string | null; onClose: () => void}) {
  const [s, setS] = useState<SessionFull | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setS(null);
    setError('');
    if (id) {
      api.session(id).then(setS, e => setError(String(e.message ?? e)));
    }
  }, [id]);

  const setOpen = (o: boolean) => {
    if (!o) {
      onClose();
    }
  };

  return (
    <Drawer isOpen={id != null} onOpenChange={setOpen} label={`Session ${id ?? ''}`} width={560}>
      <Layout
        header={
          <DrawerHeader title={s ? fmtDate(s.date) : 'Session'} subtitle={s?.topic || s?.id} onOpenChange={setOpen} />
        }
        content={
          <LayoutContent>
            {!s && !error && <Spinner label="Loading" />}
            {error && <Banner status="error" title="Could not load the session" description={error} />}
            {s && (
              <VStack gap={6}>
                {s.summary && <Text>{s.summary}</Text>}
                <MetadataList columns="multi" label={{position: 'top'}}>
                  <MetadataListItem label="Minutes">{String(s.duration_minutes ?? 0)}</MetadataListItem>
                  <MetadataListItem label="Size">{s.size || 'not set'}</MetadataListItem>
                  <MetadataListItem label="Input">{s.input_mode || 'not set'}</MetadataListItem>
                  <MetadataListItem label="Accuracy">
                    {s.accuracy == null ? 'not set' : `${Math.round(s.accuracy * 100)}%`}
                  </MetadataListItem>
                  <MetadataListItem label="Skills">{s.skills.join(', ') || 'not set'}</MetadataListItem>
                  <MetadataListItem label="Id">{s.id}</MetadataListItem>
                </MetadataList>
                <VStack gap={2}>
                  <Heading level={4}>Errors</Heading>
                  {s.errors.length === 0 ? (
                    <Text color="secondary">No errors logged for this session.</Text>
                  ) : (
                    <Table<SessionErrorRow>
                      data={s.errors.map((e, i) => ({...e, rowid: i}))}
                      columns={errorColumns}
                      idKey="rowid"
                      density="compact"
                    />
                  )}
                </VStack>
                <VStack gap={2}>
                  <Heading level={4}>Listening</Heading>
                  {s.listening.length === 0 ? (
                    <Text color="secondary">No listening results for this session.</Text>
                  ) : (
                    <VStack gap={2}>
                      {s.listening.map((l, i) => (
                        <HStack key={i} gap={3} vAlign="center" hAlign="between">
                          <Text>{l.sentence}</Text>
                          <Badge label={RESULT[l.result]?.label ?? l.result} variant={RESULT[l.result]?.variant ?? 'neutral'} />
                        </HStack>
                      ))}
                    </VStack>
                  )}
                </VStack>
                {s.reviews.length > 0 && (
                  <VStack gap={2}>
                    <Heading level={4}>Cards reviewed</Heading>
                    <VStack gap={1}>
                      {s.reviews.map((r, i) => (
                        <HStack key={i} gap={3} hAlign="between">
                          <Text>{r.content ?? r.item_id}</Text>
                          <Text color="secondary">
                            {QUALITY_NAME[r.quality] ?? r.quality}
                            {r.interval_after != null ? `, next in ${daysLabel(r.interval_after)}` : ''}
                          </Text>
                        </HStack>
                      ))}
                    </VStack>
                  </VStack>
                )}
              </VStack>
            )}
          </LayoutContent>
        }
      />
    </Drawer>
  );
}

const COMPARATORS: Partial<Record<string, TableSortComparator<SessionRow>>> = {
  date: (a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id),
  duration_minutes: (a, b) => (a.duration_minutes ?? 0) - (b.duration_minutes ?? 0),
  errors: (a, b) => a.errors - b.errors,
};

export default function Sessions() {
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState('');
  const [openId, setOpenId] = useState<string | null>(idFromHash);

  useEffect(() => {
    api.sessions().then(r => setRows(r.sessions), e => setError(String(e.message ?? e)));
    const onHash = () => setOpenId(idFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const cols = useMemo<TableColumn<SessionRow>[]>(
    () => [
      {
        key: 'date',
        header: 'Date',
        width: pixel(130),
        sortable: true,
        renderCell: s => <Link href={`#/sessions/${encodeURIComponent(s.id)}`}>{fmtDate(s.date)}</Link>,
      },
      {
        key: 'topic',
        header: 'Topic',
        width: proportional(2),
        renderCell: s => <Text maxLines={1}>{s.topic || s.summary || s.id}</Text>,
      },
      {
        key: 'duration_minutes',
        header: 'Minutes',
        width: pixel(90),
        align: 'end',
        sortable: true,
        renderCell: s => <Text hasTabularNumbers>{s.duration_minutes ?? 0}</Text>,
      },
      {
        key: 'skills',
        header: 'Skills',
        width: proportional(1),
        renderCell: s => <Text color="secondary" maxLines={1}>{s.skills.join(', ')}</Text>,
      },
      {
        key: 'errors',
        header: 'Errors',
        width: pixel(80),
        align: 'end',
        sortable: true,
        renderCell: s => <Text hasTabularNumbers>{s.errors}</Text>,
      },
    ],
    [],
  );
  const {sortedData, sortConfig} = useTableSortableState<SessionRow>({data: rows ?? [], comparators: COMPARATORS});
  const sortPlugin = useTableSortable<SessionRow>(sortConfig);

  return (
    <Layout
      height="fill"
      contentWidth={1040}
      content={
        <LayoutContent padding={0}>
          <VStack padding={4} gap={6}>
            <VStack gap={2}>
              <HStack gap={3} vAlign="center" wrap="wrap">
                <StackItem size="fill">
                  <Heading level={1}>Sessions</Heading>
                </StackItem>
                <Text color="secondary">{rows ? `${rows.length} recorded` : ''}</Text>
              </HStack>
              <Text color="secondary">
                Practice sessions, and one app-review row per day you review cards here.
              </Text>
            </VStack>
            {error && <Banner status="error" title="Could not load sessions" description={error} />}
            {rows === null && !error ? (
              <Spinner label="Loading" />
            ) : rows && rows.length === 0 ? (
              <EmptyState title="No sessions yet" description="Start one on the Practice page." />
            ) : (
              <Table<SessionRow>
                data={sortedData}
                columns={cols}
                idKey="id"
                density="balanced"
                dividers="rows"
                hasHover
                textOverflow="truncate"
                plugins={{sort: sortPlugin}}
              />
            )}
          </VStack>
          <SessionDrawer
            id={openId}
            onClose={() => {
              setOpenId(null);
              if (window.location.hash !== '#/sessions') {
                window.history.replaceState(null, '', '#/sessions');
              }
            }}
          />
        </LayoutContent>
      }
    />
  );
}
