// Scaffolded from the Astryx `blank` page template (Layout + LayoutContent); the review card
// is built from Card, Stack, Heading, Text, Button, Kbd and ProgressBar inside it.
//
// Grades map to SM-2 quality: Again 1, Hard 3, Good 4, Easy 5. The interval each button shows
// comes from the server's preview endpoint, which runs the same sm2() the review uses.

import {useCallback, useEffect, useRef, useState} from 'react';
import {Layout, LayoutContent} from '@astryxdesign/core/Layout';
import {HStack, StackItem, VStack} from '@astryxdesign/core/Stack';
import {Heading, Text} from '@astryxdesign/core/Text';
import {Card} from '@astryxdesign/core/Card';
import {Button} from '@astryxdesign/core/Button';
import {Badge} from '@astryxdesign/core/Badge';
import {Banner} from '@astryxdesign/core/Banner';
import {Divider} from '@astryxdesign/core/Divider';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Grid} from '@astryxdesign/core/Grid';
import {Kbd} from '@astryxdesign/core/Kbd';
import {List, ListItem} from '@astryxdesign/core/List';
import {MetadataList, MetadataListItem} from '@astryxdesign/core/MetadataList';
import {ProgressBar} from '@astryxdesign/core/ProgressBar';
import {Spinner} from '@astryxdesign/core/Spinner';
import {Center} from '@astryxdesign/core/Center';
import {Icon} from '@astryxdesign/core/Icon';
import {CheckCircleIcon, EyeIcon} from '@heroicons/react/24/outline';
import {api, daysLabel} from '../api';
import type {Card as DueCard, PreviewOption} from '../api';
import {HearIt} from '../HearIt';

const GRADES = [
  {key: '1', quality: 1, label: 'Again', hint: 'Incorrect response; the correct one remembered', variant: 'destructive' as const},
  {key: '2', quality: 3, label: 'Hard', hint: 'Correct with serious difficulty', variant: 'secondary' as const},
  {key: '3', quality: 4, label: 'Good', hint: 'Correct after a hesitation', variant: 'primary' as const},
  {key: '4', quality: 5, label: 'Easy', hint: 'Perfect response', variant: 'secondary' as const},
];

type Counts = Record<number, number>;

function isErrorCard(c: DueCard) {
  return c.kind === 'error_pattern';
}

function frontText(c: DueCard): string {
  return (isErrorCard(c) ? c.content : c.headword || c.content) ?? '';
}

function spokenText(c: DueCard): string {
  return (isErrorCard(c) ? c.answer : c.headword || c.content) ?? '';
}

function CardFront({card}: {card: DueCard}) {
  const kind =
    card.kind === 'error_pattern' ? 'Error pattern' : card.kind === 'grammar' ? 'Grammar' : 'Word';
  return (
    <VStack gap={3} hAlign="center">
      <HStack gap={2} hAlign="center" wrap="wrap">
        <Badge label={kind} variant={isErrorCard(card) ? 'warning' : 'info'} />
        {card.level && <Badge label={card.level} />}
      </HStack>
      {isErrorCard(card) && (
        <Text color="secondary" justify="center">
          This was said in a session. What is the correct form?
        </Text>
      )}
      <Heading level={2} type="display-3" justify="center">
        {frontText(card)}
      </Heading>
    </VStack>
  );
}

function CardBack({card}: {card: DueCard}) {
  if (isErrorCard(card)) {
    return (
      <VStack gap={4}>
        <VStack gap={1} hAlign="center">
          <Text type="supporting">Correct</Text>
          <Heading level={3} justify="center">
            {card.answer ?? ''}
          </Heading>
        </VStack>
        <MetadataList columns="multi" label={{position: 'top'}}>
          <MetadataListItem label="Category">{card.category || 'not set'}</MetadataListItem>
          {card.severity && <MetadataListItem label="Severity">{card.severity}</MetadataListItem>}
          {card.context && <MetadataListItem label="Context">{card.context}</MetadataListItem>}
        </MetadataList>
        <HStack hAlign="center">
          <HearIt text={spokenText(card)} />
        </HStack>
      </VStack>
    );
  }
  return (
    <VStack gap={4}>
      <VStack gap={1} hAlign="center">
        <Heading level={3} justify="center">
          {card.gloss || card.answer || 'no gloss yet'}
        </Heading>
        {card.forms && (
          <Text color="secondary" justify="center">
            {card.forms}
          </Text>
        )}
      </VStack>
      {card.definition && (
        <VStack gap={1}>
          <Text type="supporting">På dansk</Text>
          <Text>{card.definition}</Text>
        </VStack>
      )}
      {card.examples.length > 0 && (
        <VStack gap={1}>
          <Text type="supporting">Examples</Text>
          <List density="compact" listStyle="disc">
            {card.examples.slice(0, 3).map(ex => (
              <ListItem key={ex} label={<Text>{ex}</Text>} />
            ))}
          </List>
        </VStack>
      )}
      <HStack hAlign="center">
        <HearIt text={spokenText(card)} />
      </HStack>
    </VStack>
  );
}

function EndScreen({counts, total}: {counts: Counts; total: number}) {
  return (
    <Card>
      <VStack gap={6} padding={4}>
        <EmptyState
          icon={<Icon icon={CheckCircleIcon} size="lg" color="success" />}
          title="Review finished"
          description={`You reviewed ${total} ${total === 1 ? 'card' : 'cards'}. Each one is scheduled again by SM-2.`}
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
          <Button label="Open the word bank" href="#/words" />
        </HStack>
      </VStack>
    </Card>
  );
}

export default function Review() {
  const [cards, setCards] = useState<DueCard[] | null>(null);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [options, setOptions] = useState<PreviewOption[] | null>(null);
  const [counts, setCounts] = useState<Counts>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const shownAt = useRef(0);

  useEffect(() => {
    api.due().then(d => setCards(d.cards), e => setError(String(e.message ?? e)));
  }, []);

  const card = cards && index < cards.length ? cards[index] : null;

  useEffect(() => {
    if (!card) {
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
  }, [card]);

  const grade = useCallback(
    async (quality: number) => {
      if (!card || !revealed || busy) {
        return;
      }
      setBusy(true);
      setError('');
      try {
        await api.review(card.item_id, quality, (Date.now() - shownAt.current) / 1000);
        setCounts(c => ({...c, [quality]: (c[quality] ?? 0) + 1}));
        setRevealed(false);
        setIndex(i => i + 1);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [card, revealed, busy],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      if (e.key === ' ' && card && !revealed) {
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
  }, [card, revealed, grade]);

  const total = cards?.length ?? 0;
  const reviewed = Object.values(counts).reduce((a, b) => a + b, 0);

  let body;
  if (!cards && !error) {
    body = (
      <Center minHeight={240}>
        <Spinner size="lg" label="Loading due cards" />
      </Center>
    );
  } else if (cards && total === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<Icon icon={CheckCircleIcon} size="lg" color="success" />}
          title="Nothing is due"
          description="Every card is scheduled for a later day. Come back tomorrow, or practise speaking with /dansk."
          actions={<Button label="Back to overview" href="#/" />}
        />
      </Card>
    );
  } else if (cards && !card) {
    body = <EndScreen counts={counts} total={reviewed} />;
  } else if (card) {
    const byQ = new Map(options?.map(o => [o.quality, o]) ?? []);
    body = (
      <VStack gap={4}>
        <ProgressBar
          label={`Card ${index + 1} of ${total}`}
          value={index}
          max={total}
          hasValueLabel
          formatValueLabel={() => `${reviewed} done, ${total - index} left`}
        />
        <Card elevation="low">
          <VStack gap={6} padding={4}>
            <CardFront card={card} />
            {revealed ? (
              <>
                <Divider />
                <CardBack card={card} />
              </>
            ) : (
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
          <VStack gap={2}>
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
                      isDisabled={!o}
                      onClick={() => void grade(g.quality)}
                    />
                    <HStack gap={2} hAlign="center" vAlign="center">
                      <Kbd keys={g.key} />
                      <Text type="supporting" hasTabularNumbers>
                        {o ? `next in ${daysLabel(o.interval_days)}` : 'working out the interval'}
                      </Text>
                    </HStack>
                  </VStack>
                );
              })}
            </Grid>
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
            <HStack gap={3} vAlign="center" wrap="wrap">
              <StackItem size="fill">
                <VStack gap={1}>
                  <Heading level={1}>Review</Heading>
                  <Text color="secondary">
                    Due cards, oldest first. Reveal with Space, grade with keys 1 to 4.
                  </Text>
                </VStack>
              </StackItem>
            </HStack>
            {error && <Banner status="error" title="Something went wrong" description={error} />}
            {body}
          </VStack>
        </LayoutContent>
      }
    />
  );
}
