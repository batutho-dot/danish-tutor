// Scaffolded from the Astryx `blank` page template (Layout + LayoutContent); the review card
// is built from Card, Stack, Heading, Text, Button, Kbd and ProgressBar inside it.
//
// Grades map to SM-2 quality: Again 1, Hard 3, Good 4, Easy 5. The interval each button shows
// comes from the server's preview endpoint, which runs the same sm2() the review uses.
//
// Same-day re-drill (Wozniak 1990, step 7: repeat in the same session every item that scored
// below 4 until it scores at least 4): Again and Hard put the card back at the end of this
// review. Our reading: the FIRST grade of the day is the one stored and scheduled; the
// re-drill grades are practice only and change nothing in the database.

import {useCallback, useEffect, useRef, useState} from 'react';
import {Layout, LayoutContent} from '@astryxdesign/core/Layout';
import {HStack, StackItem, VStack} from '@astryxdesign/core/Stack';
import {Heading, Text} from '@astryxdesign/core/Text';
import {Card} from '@astryxdesign/core/Card';
import {Button} from '@astryxdesign/core/Button';
import {Banner} from '@astryxdesign/core/Banner';
import {Divider} from '@astryxdesign/core/Divider';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Grid} from '@astryxdesign/core/Grid';
import {Kbd} from '@astryxdesign/core/Kbd';
import {List, ListItem} from '@astryxdesign/core/List';
import {ProgressBar} from '@astryxdesign/core/ProgressBar';
import {Spinner} from '@astryxdesign/core/Spinner';
import {Center} from '@astryxdesign/core/Center';
import {Icon} from '@astryxdesign/core/Icon';
import {ArrowPathIcon, CheckCircleIcon, EyeIcon, WrenchScrewdriverIcon} from '@heroicons/react/24/outline';
import {DATA_CHANGED, api, daysLabel, fmtDate} from '../api';
import type {Card as DueCard, PreviewOption} from '../api';
import {HearIt} from '../HearIt';
import {FixCardDrawer} from '../FixCardDrawer';
import {splitPairs} from '../cardText';

const GRADES = [
  {key: '1', quality: 1, label: 'Again', hint: 'Incorrect response; the correct one remembered', variant: 'destructive' as const},
  {key: '2', quality: 3, label: 'Hard', hint: 'Correct with serious difficulty', variant: 'secondary' as const},
  {key: '3', quality: 4, label: 'Good', hint: 'Correct after a hesitation', variant: 'primary' as const},
  {key: '4', quality: 5, label: 'Easy', hint: 'Perfect response', variant: 'secondary' as const},
];

type Counts = Record<number, number>;
type Entry = {card: DueCard; redrill: boolean};

function isError(c: DueCard) {
  return c.kind === 'error_pattern';
}

function pairsOf(c: DueCard): [string, string][] {
  return c.pairs && c.pairs.length > 0 ? c.pairs : splitPairs(c.content, c.answer);
}

function spokenText(c: DueCard): string {
  return (isError(c) ? pairsOf(c).map(p => p[1]).join('. ') : c.headword || c.content) ?? '';
}

function cardTitle(c: DueCard): string {
  if (isError(c)) {
    return c.mistake_date ? `A mistake from ${fmtDate(c.mistake_date)}` : 'A mistake from an earlier session';
  }
  return c.kind === 'grammar' ? 'Grammar' : 'Word';
}

function ErrorCard({card, revealed}: {card: DueCard; revealed: boolean}) {
  const pairs = pairsOf(card);
  return (
    <VStack gap={4}>
      {card.description && <Text>{card.description}</Text>}
      {card.context && (
        <Text type="supporting" color="secondary">
          Context: {card.context}
        </Text>
      )}
      <Divider />
      {pairs.map(([said, correct], i) => (
        <VStack key={i} gap={2}>
          {pairs.length > 1 && (
            <Text type="supporting" color="secondary">
              Mistake {i + 1} of {pairs.length}
            </Text>
          )}
          <Grid columns={{minWidth: 200, repeat: 'fit'}} gap={4}>
            <VStack gap={1}>
              <Text type="supporting" color="secondary">
                You said
              </Text>
              <Text size="lg" hasStrikethrough={revealed}>
                {said || 'not recorded'}
              </Text>
            </VStack>
            <VStack gap={1}>
              <Text type="supporting" color="secondary">
                Correct
              </Text>
              {revealed ? (
                <Text size="lg" weight="semibold">
                  {correct || 'not recorded'}
                </Text>
              ) : (
                <Text size="lg" color="secondary">
                  ?
                </Text>
              )}
            </VStack>
          </Grid>
        </VStack>
      ))}
      {revealed && (
        <HStack>
          <HearIt text={spokenText(card)} />
        </HStack>
      )}
    </VStack>
  );
}

function WordCard({card, revealed}: {card: DueCard; revealed: boolean}) {
  return (
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={2} type="display-3">
          {card.headword || card.content || ''}
        </Heading>
        {card.level && (
          <Text type="supporting" color="secondary">
            Level {card.level}
          </Text>
        )}
      </VStack>
      {revealed && (
        <>
          <Divider />
          <VStack gap={1}>
            <Heading level={3}>{card.gloss || card.answer || 'no gloss yet'}</Heading>
            {card.forms && <Text color="secondary">{card.forms}</Text>}
          </VStack>
          {card.definition && (
            <VStack gap={1}>
              <Text type="supporting" color="secondary">
                På dansk
              </Text>
              <Text>{card.definition}</Text>
            </VStack>
          )}
          {card.examples.length > 0 && (
            <VStack gap={1}>
              <Text type="supporting" color="secondary">
                Examples
              </Text>
              <List density="compact" listStyle="disc">
                {card.examples.slice(0, 3).map(ex => (
                  <ListItem key={ex} label={<Text>{ex}</Text>} />
                ))}
              </List>
            </VStack>
          )}
          <HStack>
            <HearIt text={spokenText(card)} />
          </HStack>
        </>
      )}
    </VStack>
  );
}

function EndScreen({counts, total, redrills}: {counts: Counts; total: number; redrills: number}) {
  return (
    <Card>
      <VStack gap={6} padding={4}>
        <EmptyState
          icon={<Icon icon={CheckCircleIcon} size="lg" color="success" />}
          title="Review finished"
          description={
            `You reviewed ${total} ${total === 1 ? 'card' : 'cards'}; each is scheduled again by SM-2.` +
            (redrills > 0 ? ` You also went over ${redrills} again until you knew ${redrills === 1 ? 'it' : 'them'}.` : '')
          }
        />
        <Grid columns={{minWidth: 110, repeat: 'fit'}} gap={3}>
          {GRADES.map(g => (
            <Card key={g.quality} variant="muted">
              <VStack gap={1} hAlign="center">
                <Heading level={2}>{counts[g.quality] ?? 0}</Heading>
                <Text color="secondary">{g.label}</Text>
              </VStack>
            </Card>
          ))}
        </Grid>
        <HStack hAlign="center" gap={3} wrap="wrap">
          <Button label="Back to overview" variant="primary" href="#/" />
          <Button label="Practise speaking" href="#/practice" />
        </HStack>
      </VStack>
    </Card>
  );
}

function hintFor(quality: number, o: PreviewOption | undefined, redrill: boolean): string {
  if (redrill) {
    return quality < 4 ? 'again now' : 'done for today';
  }
  if (!o) {
    return 'working out the interval';
  }
  return quality < 4 ? `again now, then ${daysLabel(o.interval_days)}` : `in ${daysLabel(o.interval_days)}`;
}

export default function Review() {
  const [queue, setQueue] = useState<Entry[] | null>(null);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [options, setOptions] = useState<PreviewOption[] | null>(null);
  const [counts, setCounts] = useState<Counts>({});
  const [redrills, setRedrills] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fixing, setFixing] = useState<DueCard | null>(null);
  const shownAt = useRef(0);
  const started = useRef(false);

  const load = useCallback(() => {
    api.due().then(
      d => {
        setQueue(d.cards.map(card => ({card, redrill: false})));
        setIndex(0);
        setRevealed(false);
        setCounts({});
        setRedrills(0);
        started.current = false;
      },
      e => setError(String(e.message ?? e)),
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const entry = queue && index < queue.length ? queue[index] : null;
  const card = entry?.card ?? null;

  // Refetch when the window gets focus again or a practice session saved, but never in the
  // middle of a review (that would lose the re-drill queue).
  useEffect(() => {
    const onChange = () => {
      if (!started.current || (queue && index >= queue.length)) {
        load();
      }
    };
    window.addEventListener('focus', onChange);
    window.addEventListener(DATA_CHANGED, onChange);
    return () => {
      window.removeEventListener('focus', onChange);
      window.removeEventListener(DATA_CHANGED, onChange);
    };
  }, [load, queue, index]);

  useEffect(() => {
    if (!card || entry?.redrill) {
      return;
    }
    shownAt.current = Date.now();
    setOptions(null);
    let live = true;
    api.preview(card.item_id).then(
      p => live && setOptions(p.options),
      e => live && setError(String(e.message ?? e)),
    );
    return () => {
      live = false;
    };
  }, [card, entry?.redrill]);

  const grade = useCallback(
    async (quality: number) => {
      if (!entry || !revealed || busy) {
        return;
      }
      setBusy(true);
      setError('');
      try {
        if (!entry.redrill) {
          await api.review(entry.card.item_id, quality, (Date.now() - shownAt.current) / 1000);
          setCounts(c => ({...c, [quality]: (c[quality] ?? 0) + 1}));
        }
        started.current = true;
        if (quality < 4) {
          setQueue(q => (q ? [...q, {card: entry.card, redrill: true}] : q));
          if (!entry.redrill) {
            setRedrills(n => n + 1);
          }
        }
        setRevealed(false);
        setIndex(i => i + 1);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [entry, revealed, busy],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (fixing || (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable))) {
        return;
      }
      // Space on a focused button (Fix this card, Hear it) presses that button, as usual.
      const onButton = t?.closest('button, a, [role="button"]') != null;
      if (e.key === ' ' && card && !revealed && !onButton) {
        e.preventDefault();
        setRevealed(true);
        return;
      }
      const g = GRADES.find(x => x.key === e.key);
      if (g && revealed) {
        e.preventDefault();
        void grade(g.quality);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [card, revealed, grade, fixing]);

  const patchCard = (patch: Partial<DueCard>) => {
    if (!fixing) {
      return;
    }
    const id = fixing.item_id;
    setQueue(q => (q ? q.map(x => (x.card.item_id === id ? {...x, card: {...x.card, ...patch}} : x)) : q));
  };

  const dropCard = () => {
    if (!fixing) {
      return;
    }
    const id = fixing.item_id;
    setQueue(q => {
      if (!q) {
        return q;
      }
      const before = q.slice(0, index).filter(x => x.card.item_id !== id).length;
      setIndex(before);
      setRevealed(false);
      return q.filter(x => x.card.item_id !== id);
    });
  };

  const total = queue?.filter(x => !x.redrill).length ?? 0;
  const reviewed = Object.values(counts).reduce((a, b) => a + b, 0);
  const left = queue ? queue.length - index : 0;

  let body;
  if (!queue && !error) {
    body = (
      <Center minHeight={240}>
        <Spinner size="lg" label="Loading due cards" />
      </Center>
    );
  } else if (queue && queue.length === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<Icon icon={CheckCircleIcon} size="lg" color="success" />}
          title="Nothing is due"
          description="Every card is scheduled for a later day. Come back tomorrow, or practise speaking."
          actions={<Button label="Practise speaking" href="#/practice" />}
        />
      </Card>
    );
  } else if (queue && !entry) {
    body = <EndScreen counts={counts} total={reviewed} redrills={redrills} />;
  } else if (entry && card) {
    const byQ = new Map(options?.map(o => [o.quality, o]) ?? []);
    const firstReview = !entry.redrill && card.repetitions === 0;
    body = (
      <VStack gap={4}>
        <ProgressBar
          label={`${reviewed} of ${total} reviewed`}
          value={reviewed}
          max={Math.max(total, 1)}
          hasValueLabel
          formatValueLabel={() => `${left} to go${redrills > 0 ? ` (${queue!.slice(index).filter(x => x.redrill).length} again)` : ''}`}
        />
        <Card elevation="low">
          <VStack gap={6} padding={4}>
            <HStack gap={3} vAlign="center" wrap="wrap">
              <StackItem size="fill">
                <VStack gap={0}>
                  <Heading level={3}>{cardTitle(card)}</Heading>
                  {entry.redrill && (
                    <HStack gap={1} vAlign="center">
                      <Icon icon={ArrowPathIcon} size="sm" color="secondary" />
                      <Text type="supporting" color="secondary">
                        Once more, from earlier in this review
                      </Text>
                    </HStack>
                  )}
                </VStack>
              </StackItem>
              <Button
                label="Fix this card"
                variant="ghost"
                size="sm"
                icon={<Icon icon={WrenchScrewdriverIcon} size="sm" />}
                onClick={() => setFixing(card)}
              />
            </HStack>
            {isError(card) ? <ErrorCard card={card} revealed={revealed} /> : <WordCard card={card} revealed={revealed} />}
            {!revealed && (
              <VStack gap={2} hAlign="center">
                <Button
                  label="Show answer"
                  variant="primary"
                  size="lg"
                  icon={<Icon icon={EyeIcon} size="md" />}
                  onClick={() => setRevealed(true)}
                />
                <HStack gap={2} vAlign="center" hAlign="center">
                  <Text type="supporting">or press</Text>
                  <Kbd keys="space" />
                </HStack>
              </VStack>
            )}
          </VStack>
        </Card>
        {revealed && (
          <VStack gap={3}>
            <Text type="supporting">How well did you know it?</Text>
            <Grid columns={{minWidth: 140, repeat: 'fit'}} gap={3}>
              {GRADES.map(g => {
                const o = byQ.get(g.quality);
                return (
                  <VStack key={g.quality} gap={1}>
                    <Button
                      label={g.label}
                      variant={g.variant}
                      size="lg"
                      width="100%"
                      tooltip={`${g.hint}. SM-2 quality ${g.quality}.`}
                      isLoading={busy}
                      isDisabled={!entry.redrill && !o}
                      onClick={() => void grade(g.quality)}
                    />
                    <HStack gap={2} hAlign="center" vAlign="center">
                      <Kbd keys={g.key} />
                      <Text type="supporting" hasTabularNumbers>
                        {hintFor(g.quality, o, entry.redrill)}
                      </Text>
                    </HStack>
                  </VStack>
                );
              })}
            </Grid>
            {firstReview && (
              <Text type="supporting" color="secondary">
                First review: every grade schedules 1 day. Gaps grow from the second review (6 days, then longer).
              </Text>
            )}
            {entry.redrill && (
              <Text type="supporting" color="secondary">
                Practice round: your first answer today already set the schedule, so this grade changes nothing saved.
              </Text>
            )}
          </VStack>
        )}
      </VStack>
    );
  }

  return (
    <Layout
      height="fill"
      contentWidth={720}
      content={
        <LayoutContent padding={6}>
          <VStack gap={6}>
            <VStack gap={1}>
              <Heading level={1}>Review</Heading>
              <Text color="secondary">
                Due cards, oldest first. Space shows the answer, keys 1 to 4 grade it. Again and Hard come back at the end.
              </Text>
            </VStack>
            {error && <Banner status="error" title="Something went wrong" description={error} />}
            {body}
          </VStack>
          <FixCardDrawer card={fixing} onClose={() => setFixing(null)} onSaved={patchCard} onDeleted={dropCard} />
        </LayoutContent>
      }
    />
  );
}
