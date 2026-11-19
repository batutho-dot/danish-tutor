// Scaffolded from the Astryx `table-page` template (Searchable Table): masthead, a filter row,
// then a sortable Table, with LayoutContent padding 0 and the padding moved to the VStack.
// Content replaced; a Drawer shows one word's details, edit form and delete.

import {useCallback, useEffect, useMemo, useState} from 'react';
import {HStack, Layout, LayoutContent, LayoutFooter, StackItem, VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {AlertDialog} from '@astryxdesign/core/AlertDialog';
import {Badge} from '@astryxdesign/core/Badge';
import {Banner} from '@astryxdesign/core/Banner';
import {Button} from '@astryxdesign/core/Button';
import {Drawer, DrawerHeader} from '@astryxdesign/core/Drawer';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Icon} from '@astryxdesign/core/Icon';
import {Link} from '@astryxdesign/core/Link';
import {List, ListItem} from '@astryxdesign/core/List';
import {MetadataList, MetadataListItem} from '@astryxdesign/core/MetadataList';
import {ProgressBar} from '@astryxdesign/core/ProgressBar';
import {SegmentedControl, SegmentedControlItem} from '@astryxdesign/core/SegmentedControl';
import {Selector} from '@astryxdesign/core/Selector';
import {Spinner} from '@astryxdesign/core/Spinner';
import {TextArea} from '@astryxdesign/core/TextArea';
import {TextInput} from '@astryxdesign/core/TextInput';
import {useToast} from '@astryxdesign/core/Toast';
import {Table, pixel, proportional, useTableSortable, useTableSortableState} from '@astryxdesign/core/Table';
import type {TableColumn, TableSortComparator} from '@astryxdesign/core/Table';
import {MagnifyingGlassIcon, PencilSquareIcon, TrashIcon} from '@heroicons/react/24/outline';
import {api, daysLabel, fmtDate} from '../api';
import type {ReviewRow, WordDetail, WordEdit, WordRow} from '../api';
import {HearIt} from '../HearIt';

// ============= TABLE =============

const QUALITY_NAME: Record<number, string> = {0: 'Blackout', 1: 'Again', 2: 'Wrong', 3: 'Hard', 4: 'Good', 5: 'Easy'};

function columns(open: (id: number) => void): TableColumn<WordRow>[] {
  return [
    {
      key: 'headword',
      header: 'Headword',
      width: proportional(2),
      sortable: true,
      renderCell: item => (
        <Link onClick={() => open(item.id)} weight="medium">
          {item.headword}
        </Link>
      ),
    },
    {
      key: 'gloss',
      header: 'Gloss',
      width: proportional(2),
      sortable: true,
      renderCell: item => (
        <Text color="secondary" maxLines={1}>
          {item.gloss ?? ''}
        </Text>
      ),
    },
    {
      key: 'level',
      header: 'Level',
      width: pixel(80),
      sortable: true,
      renderCell: item => <Text>{item.level ?? ''}</Text>,
    },
    {
      key: 'mastery_level',
      header: 'Mastery',
      width: pixel(110),
      sortable: true,
      renderCell: item => (
        <ProgressBar
          label={`${item.headword} mastery`}
          isLabelHidden
          value={item.mastery_level ?? 0}
          max={5}
          variant={(item.mastery_level ?? 0) >= 3 ? 'success' : 'accent'}
        />
      ),
    },
    {
      key: 'due_date',
      header: 'Next due',
      width: pixel(140),
      sortable: true,
      renderCell: item =>
        item.is_due ? (
          <Badge label={`Due ${fmtDate(item.due_date)}`} variant="warning" />
        ) : (
          <Text color="secondary">{fmtDate(item.due_date)}</Text>
        ),
    },
  ];
}

const COMPARATORS: Partial<Record<string, TableSortComparator<WordRow>>> = {
  headword: (a, b) => a.headword.localeCompare(b.headword, 'da'),
  gloss: (a, b) => (a.gloss ?? '').localeCompare(b.gloss ?? ''),
  level: (a, b) => (a.level ?? '').localeCompare(b.level ?? ''),
  mastery_level: (a, b) => (a.mastery_level ?? -1) - (b.mastery_level ?? -1),
  due_date: (a, b) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999'),
};

// ============= DETAIL DRAWER =============

const EDIT_FIELDS: {key: keyof WordEdit; label: string; long?: boolean}[] = [
  {key: 'headword', label: 'Headword'},
  {key: 'gloss', label: 'Gloss (English)'},
  {key: 'forms', label: 'Forms'},
  {key: 'definition', label: 'Definition (Danish)', long: true},
  {key: 'pos', label: 'Part of speech'},
  {key: 'gender', label: 'Gender'},
  {key: 'level', label: 'Level'},
  {key: 'notes', label: 'Notes', long: true},
];

const reviewColumns: TableColumn<ReviewRow>[] = [
  {key: 'date', header: 'Date', width: proportional(1), renderCell: r => <Text>{fmtDate(r.date)}</Text>},
  {key: 'quality', header: 'Grade', width: pixel(90), renderCell: r => <Text>{QUALITY_NAME[r.quality] ?? r.quality}</Text>},
  {
    key: 'interval_after',
    header: 'Next gap',
    width: pixel(90),
    align: 'end',
    renderCell: r => <Text hasTabularNumbers>{r.interval_after == null ? '' : daysLabel(r.interval_after)}</Text>,
  },
];

function WordDrawer({
  wordId,
  onClose,
  onChanged,
}: {
  wordId: number | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [w, setW] = useState<WordDetail | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const showToast = useToast();

  useEffect(() => {
    setW(null);
    setError('');
    setEditing(false);
    if (wordId == null) {
      return;
    }
    api.word(wordId).then(setW, e => setError(String(e.message ?? e)));
  }, [wordId]);

  const startEdit = () => {
    if (!w) {
      return;
    }
    setForm(Object.fromEntries(EDIT_FIELDS.map(f => [f.key, (w[f.key] as string | null) ?? ''])));
    setError('');
    setEditing(true);
  };

  const save = async () => {
    if (!w) {
      return;
    }
    const changed: WordEdit = {};
    for (const f of EDIT_FIELDS) {
      const now = form[f.key]?.trim() ?? '';
      const was = ((w[f.key] as string | null) ?? '').trim();
      if (now !== was) {
        changed[f.key] = now === '' ? null : now;
      }
    }
    if (Object.keys(changed).length === 0) {
      setEditing(false);
      return;
    }
    try {
      const updated = await api.editWord(w.id, changed);
      setW(updated);
      setEditing(false);
      showToast({body: `Saved ${updated.headword}`});
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async () => {
    if (!w) {
      return;
    }
    setDeleting(true);
    try {
      await api.deleteWord(w.id);
      setConfirm(false);
      showToast({body: `Deleted ${w.headword}`});
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setConfirm(false);
    } finally {
      setDeleting(false);
    }
  };

  const item = w?.items[0];
  const open = wordId != null;
  const setOpen = (o: boolean) => {
    if (!o) {
      onClose();
    }
  };

  return (
    <>
      <Drawer isOpen={open} onOpenChange={setOpen} label={w ? `Word: ${w.headword}` : 'Word'} width={480} purpose={editing ? 'form' : 'info'}>
        <Layout
          header={
            <DrawerHeader
              title={w?.headword ?? 'Loading'}
              subtitle={w ? [w.kind === 'grammar' ? 'Grammar note' : 'Word', w.pos, w.gender, w.level].filter(Boolean).join(', ') : undefined}
              onOpenChange={setOpen}
            />
          }
          content={
            <LayoutContent>
              {!w && !error && <Spinner label="Loading" />}
              {error && <Banner status="error" title="Not saved" description={error} />}
              {w && !editing && (
                <VStack gap={6}>
                  <HStack gap={2} wrap="wrap">
                    <HearIt text={w.headword} />
                    <Button label="Edit" icon={<Icon icon={PencilSquareIcon} size="sm" />} onClick={startEdit} />
                    <Button
                      label="Delete"
                      variant="destructive"
                      icon={<Icon icon={TrashIcon} size="sm" />}
                      onClick={() => setConfirm(true)}
                    />
                  </HStack>
                  <MetadataList label={{position: 'top'}}>
                    <MetadataListItem label="Gloss">{w.gloss || 'not set'}</MetadataListItem>
                    <MetadataListItem label="Forms">{w.forms || 'not set'}</MetadataListItem>
                    <MetadataListItem label="Definition (Danish)">{w.definition || 'not set'}</MetadataListItem>
                    <MetadataListItem label="Notes">{w.notes || 'none'}</MetadataListItem>
                  </MetadataList>
                  <MetadataList columns="multi" label={{position: 'top'}}>
                    <MetadataListItem label="Learned">{fmtDate(w.learned)}</MetadataListItem>
                    <MetadataListItem label="Source">{w.source || 'not set'}</MetadataListItem>
                    <MetadataListItem label="Next due">{fmtDate(item?.due_date)}</MetadataListItem>
                    <MetadataListItem label="Mastery">{item ? `${item.mastery_level} of 5` : 'no item'}</MetadataListItem>
                    <MetadataListItem label="Easiness">{item ? item.easiness_factor.toFixed(2) : 'no item'}</MetadataListItem>
                    <MetadataListItem label="Reviews">{item ? String(item.total_reviews) : '0'}</MetadataListItem>
                  </MetadataList>
                  <VStack gap={2}>
                    <Heading level={4}>Examples</Heading>
                    {w.examples.length === 0 ? (
                      <Text color="secondary">No example sentences yet.</Text>
                    ) : (
                      <List density="compact" listStyle="disc">
                        {w.examples.map(ex => (
                          <ListItem key={ex.id} label={ex.sentence} />
                        ))}
                      </List>
                    )}
                  </VStack>
                  <VStack gap={2}>
                    <Heading level={4}>Review history</Heading>
                    {!item || item.reviews.length === 0 ? (
                      <Text color="secondary">
                        No reviews logged in this database
                        {item && item.total_reviews > 0 ? ` (${item.total_reviews} counted before import)` : ''}.
                      </Text>
                    ) : (
                      <Table<ReviewRow> data={item.reviews} columns={reviewColumns} idKey="id" density="compact" />
                    )}
                  </VStack>
                </VStack>
              )}
              {w && editing && (
                <VStack gap={4}>
                  {EDIT_FIELDS.map(f =>
                    f.long ? (
                      <TextArea
                        key={f.key}
                        label={f.label}
                        value={form[f.key] ?? ''}
                        onChange={v => setForm(s => ({...s, [f.key]: v}))}
                        rows={3}
                        isRequired={f.key === 'headword'}
                      />
                    ) : (
                      <TextInput
                        key={f.key}
                        label={f.label}
                        value={form[f.key] ?? ''}
                        onChange={v => setForm(s => ({...s, [f.key]: v}))}
                        isRequired={f.key === 'headword'}
                        width="100%"
                      />
                    ),
                  )}
                </VStack>
              )}
            </LayoutContent>
          }
          footer={
            w && editing ? (
              <LayoutFooter>
                <HStack gap={2} hAlign="end">
                  <Button label="Cancel" onClick={() => setEditing(false)} />
                  <Button label="Save" variant="primary" clickAction={save} />
                </HStack>
              </LayoutFooter>
            ) : undefined
          }
        />
      </Drawer>
      <AlertDialog
        isOpen={confirm}
        onOpenChange={setConfirm}
        title={`Delete ${w?.headword ?? 'this word'}?`}
        description="This removes the word, its examples, its review item and that item's review history from the database. It cannot be undone."
        actionLabel="Delete"
        onAction={remove}
        isActionLoading={deleting}
      />
    </>
  );
}

// ============= PAGE =============

export default function WordBank() {
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [level, setLevel] = useState('all');
  const [due, setDue] = useState('all');
  const [rows, setRows] = useState<WordRow[] | null>(null);
  const [levels, setLevels] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [openId, setOpenId] = useState<number | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => {
      api
        .words({
          q: query.trim(),
          kind: kind === 'all' ? '' : kind,
          level: level === 'all' ? '' : level,
          due: due === 'all' ? '' : due,
        })
        .then(
          r => {
            setRows(r.words);
            setLevels(r.levels);
            setError('');
          },
          e => setError(String(e.message ?? e)),
        );
    }, 150);
    return () => window.clearTimeout(t);
  }, [query, kind, level, due, version]);

  const refresh = useCallback(() => setVersion(v => v + 1), []);
  const cols = useMemo(() => columns(setOpenId), []);
  const {sortedData, sortConfig} = useTableSortableState<WordRow>({
    data: rows ?? [],
    comparators: COMPARATORS,
  });
  const sortPlugin = useTableSortable<WordRow>(sortConfig);

  const filtered = query.trim() !== '' || kind !== 'all' || level !== 'all' || due !== 'all';
  const clearAll = () => {
    setQuery('');
    setKind('all');
    setLevel('all');
    setDue('all');
  };

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
                  <Heading level={1}>Word bank</Heading>
                </StackItem>
                <Text color="secondary">{rows ? `${rows.length} shown` : ''}</Text>
              </HStack>
              <Text color="secondary">Every word and grammar note in your database. Open one to see examples, history, or to edit it.</Text>
            </VStack>

            <HStack gap={3} vAlign="end" wrap="wrap">
              <VStack width={260}>
                <TextInput
                  label="Search words"
                  isLabelHidden
                  value={query}
                  onChange={setQuery}
                  placeholder="Search headword or gloss"
                  startIcon={MagnifyingGlassIcon}
                  hasClear
                />
              </VStack>
              <Selector
                label="Type"
                isLabelHidden
                value={kind}
                onChange={v => setKind(v ?? 'all')}
                options={[
                  {value: 'all', label: 'Words and grammar'},
                  {value: 'word', label: 'Words'},
                  {value: 'grammar', label: 'Grammar'},
                ]}
              />
              <Selector
                label="Level"
                isLabelHidden
                value={level}
                onChange={v => setLevel(v ?? 'all')}
                options={[{value: 'all', label: 'All levels'}, ...levels.map(l => ({value: l, label: l}))]}
              />
              <SegmentedControl label="Due filter" value={due} onChange={setDue}>
                <SegmentedControlItem value="all" label="All" />
                <SegmentedControlItem value="due" label="Due" />
                <SegmentedControlItem value="not_due" label="Not due" />
              </SegmentedControl>
            </HStack>

            {error && <Banner status="error" title="Could not load the word bank" description={error} />}
            {rows === null && !error ? (
              <Spinner label="Loading" />
            ) : rows && rows.length === 0 ? (
              <EmptyState
                title={filtered ? 'No matching words' : 'No words yet'}
                description={filtered ? 'Nothing matches the current search and filters.' : 'Words appear here after a /dansk session or an import.'}
                actions={filtered ? <Button label="Clear filters" onClick={clearAll} /> : undefined}
              />
            ) : (
              <Table<WordRow>
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
          <WordDrawer wordId={openId} onClose={() => setOpenId(null)} onChanged={refresh} />
        </LayoutContent>
      }
    />
  );
}
