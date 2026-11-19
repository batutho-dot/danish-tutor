// Scaffolded from the Astryx `dashboard` template: headline tiles, then a chart, then tables,
// in its Layout / LayoutContent padding 6 / VStack gap 6 frame. Content replaced.

import {useEffect, useState} from 'react';
import {VStack, HStack, Layout, LayoutContent, StackItem} from '@astryxdesign/core/Layout';
import {Text, Heading} from '@astryxdesign/core/Text';
import {Card} from '@astryxdesign/core/Card';
import {Button} from '@astryxdesign/core/Button';
import {Banner} from '@astryxdesign/core/Banner';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Spinner} from '@astryxdesign/core/Spinner';
import {Center} from '@astryxdesign/core/Center';
import {BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer} from 'recharts';
import {Grid} from '@astryxdesign/core/Grid';
import {Table, proportional, pixel} from '@astryxdesign/core/Table';
import type {TableColumn} from '@astryxdesign/core/Table';
import {Divider} from '@astryxdesign/core/Divider';
import {Link} from '@astryxdesign/core/Link';
import {Icon} from '@astryxdesign/core/Icon';
import {AcademicCapIcon} from '@heroicons/react/24/outline';
import {api, fmtDate} from '../api';
import type {PatternItem, SessionRow, Summary} from '../api';

// ============= CHART =============

const barColor = 'var(--color-data-categorical-blue)';
const axisTick = {fontSize: 'var(--font-size-sm)', fill: 'var(--color-text-secondary)'};

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{payload: {date: string; minutes: number; reviews: number}}>;
}) {
  if (!active || !payload?.length) {
    return null;
  }
  const p = payload[0].payload;
  return (
    <Card padding={3} elevation="low">
      <VStack gap={1}>
        <Text type="supporting" color="secondary">
          {fmtDate(p.date)}
        </Text>
        <Text type="supporting">{p.minutes} minutes practised</Text>
        <Text type="supporting">{p.reviews} cards reviewed</Text>
      </VStack>
    </Card>
  );
}

function ActivityChart({days}: {days: Summary['days']}) {
  const data = days.map(d => ({
    ...d,
    label: new Date(`${d.date}T00:00:00`).toLocaleDateString('en-GB', {day: 'numeric', month: 'short'}),
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{top: 5, right: 10, left: 0, bottom: 5}}>
        <CartesianGrid horizontal vertical={false} stroke="var(--color-border)" />
        <XAxis dataKey="label" tick={axisTick} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={16} />
        <YAxis allowDecimals={false} tick={axisTick} axisLine={false} tickLine={false} width={30} />
        <Tooltip content={<ChartTooltip />} cursor={{fill: 'var(--color-background-muted)'}} />
        <Bar dataKey="minutes" name="Minutes" fill={barColor} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ============= TILES =============

function MetricCard({label, value, note}: {label: string; value: string; note: string}) {
  return (
    <Card>
      <VStack gap={2}>
        <Heading level={4}>{label}</Heading>
        <Heading level={2}>{value}</Heading>
        <Text type="supporting" color="secondary">
          {note}
        </Text>
      </VStack>
    </Card>
  );
}

// ============= TABLES =============

const patternColumns: TableColumn<PatternItem>[] = [
  {
    key: 'content',
    header: 'What was said',
    width: proportional(1),
    renderCell: item => (
      <Text hasStrikethrough color="secondary">
        {item.content ?? ''}
      </Text>
    ),
  },
  {
    key: 'answer',
    header: 'Correct',
    width: proportional(1),
    renderCell: item => <Text weight="medium">{item.answer ?? ''}</Text>,
  },
  {
    key: 'category',
    header: 'Category',
    width: pixel(110),
    renderCell: item => <Text color="secondary">{item.category ?? ''}</Text>,
  },
];

const sessionColumns: TableColumn<SessionRow>[] = [
  {
    key: 'date',
    header: 'Date',
    width: pixel(120),
    renderCell: item => <Link href={`#/sessions/${item.id}`}>{fmtDate(item.date)}</Link>,
  },
  {
    key: 'topic',
    header: 'Topic',
    width: proportional(1),
    renderCell: item => <Text maxLines={1}>{item.topic || item.summary || item.id}</Text>,
  },
  {
    key: 'duration_minutes',
    header: 'Minutes',
    width: pixel(80),
    align: 'end',
    renderCell: item => <Text hasTabularNumbers>{item.duration_minutes ?? 0}</Text>,
  },
];

function TableCard<T extends Record<string, unknown>>({
  title,
  linkLabel,
  linkHref,
  data,
  columns,
  idKey,
  empty,
}: {
  title: string;
  linkLabel: string;
  linkHref: string;
  data: T[];
  columns: TableColumn<T>[];
  idKey: keyof T & string;
  empty: string;
}) {
  return (
    <Card>
      <VStack gap={6}>
        <HStack hAlign="between" vAlign="center">
          <Heading level={4}>{title}</Heading>
          <Link href={linkHref}>{linkLabel}</Link>
        </HStack>
        {data.length === 0 ? (
          <Text color="secondary">{empty}</Text>
        ) : (
          <Table<T> data={data} columns={columns} idKey={idKey} density="compact" dividers="rows" hasHover />
        )}
      </VStack>
    </Card>
  );
}

// ============= MAIN COMPONENT =============

export default function Overview() {
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.summary().then(setS, e => setError(String(e.message ?? e)));
  }, []);

  if (error) {
    return (
      <Layout
        height="fill"
        content={
          <LayoutContent padding={6}>
            <Banner status="error" title="Could not load your data" description={error} />
          </LayoutContent>
        }
      />
    );
  }
  if (!s) {
    return (
      <Center height="100%">
        <Spinner size="lg" label="Loading" />
      </Center>
    );
  }

  const level = s.learner.level
    ? `Level ${s.learner.level}${s.learner.target_level ? `, aiming for ${s.learner.target_level}` : ''}`
    : 'Danish practice';

  return (
    <Layout
      height="fill"
      content={
        <LayoutContent padding={6}>
          <VStack gap={6}>
            <HStack gap={3} vAlign="center" wrap="wrap">
              <StackItem size="fill">
                <VStack gap={1}>
                  <Heading level={1}>Overview</Heading>
                  <Text color="secondary">
                    {level}. Today is {fmtDate(s.today)}.
                  </Text>
                </VStack>
              </StackItem>
              <Button
                label={s.due > 0 ? `Start review (${s.due} due)` : 'Nothing due'}
                variant="primary"
                size="lg"
                href={s.due > 0 ? '#/review' : undefined}
                isDisabled={s.due === 0}
                icon={<Icon icon={AcademicCapIcon} size="md" />}
              />
            </HStack>

            {/* Tiles */}
            <Grid columns={{minWidth: 150, repeat: 'fit'}} gap={4}>
              <MetricCard label="Due today" value={String(s.due)} note={`of ${s.items} tracked items`} />
              <MetricCard label="Words known" value={String(s.words)} note={`plus ${s.grammar} grammar notes`} />
              <MetricCard
                label="Streak"
                value={s.streak === 1 ? '1 day' : `${s.streak} days`}
                note="days in a row with a session"
              />
              <MetricCard label="This week" value={`${s.minutes_week} min`} note="practice since Monday" />
            </Grid>

            {/* Activity chart */}
            <VStack gap={3}>
              <Heading level={3}>Last 14 days</Heading>
              <Text type="supporting" color="secondary">
                Minutes of practice per day, from your recorded sessions.
              </Text>
              {s.days.some(d => d.minutes > 0 || d.reviews > 0) ? (
                <ActivityChart days={s.days} />
              ) : (
                <EmptyState
                  isCompact
                  title="No practice in the last 14 days"
                  description="Run /dansk in Claude Code or review some cards here."
                />
              )}
            </VStack>

            <Divider />

            <Grid columns={{minWidth: 320, repeat: 'fit'}} gap={4}>
              <TableCard<PatternItem>
                title="Error patterns due"
                linkLabel="Review them"
                linkHref="#/review"
                data={s.patterns_due}
                columns={patternColumns}
                idKey="id"
                empty="No error patterns are due."
              />
              <TableCard<SessionRow>
                title="Recent sessions"
                linkLabel="All sessions"
                linkHref="#/sessions"
                data={s.recent_sessions}
                columns={sessionColumns}
                idKey="id"
                empty="No sessions recorded yet."
              />
            </Grid>
          </VStack>
        </LayoutContent>
      }
    />
  );
}
