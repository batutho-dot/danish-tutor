// "Fix this card": a Drawer (same pattern as the word bank's) that edits what one review card
// shows, or deletes it. Error-pattern and other unlinked items are edited through
// PUT /api/items/<id>; a card that belongs to a word edits the word (PUT /api/words/<id>).
// Neither changes the card's schedule.

import {useEffect, useState} from 'react';
import {HStack, Layout, LayoutContent, LayoutFooter, VStack} from '@astryxdesign/core/Layout';
import {Text} from '@astryxdesign/core/Text';
import {AlertDialog} from '@astryxdesign/core/AlertDialog';
import {Banner} from '@astryxdesign/core/Banner';
import {Button} from '@astryxdesign/core/Button';
import {Drawer, DrawerHeader} from '@astryxdesign/core/Drawer';
import {Icon} from '@astryxdesign/core/Icon';
import {TextArea} from '@astryxdesign/core/TextArea';
import {TextInput} from '@astryxdesign/core/TextInput';
import {TrashIcon} from '@heroicons/react/24/outline';
import {api} from './api';
import type {Card} from './api';
import {splitPairs} from './cardText';

type Field = {key: string; label: string; long?: boolean; required?: boolean; description?: string};

const ERROR_FIELDS: Field[] = [
  {key: 'content', label: 'You said', required: true, description: 'Two mistakes? Separate them with " / " on both sides.'},
  {key: 'answer', label: 'Correct', required: true},
  {key: 'description', label: 'What the mistake is about', long: true},
  {key: 'context', label: 'Where it came up', long: true},
];
const ITEM_FIELDS: Field[] = [
  {key: 'content', label: 'Front', required: true},
  {key: 'answer', label: 'Answer', required: true},
  {key: 'description', label: 'Note', long: true},
];
const WORD_FIELDS: Field[] = [
  {key: 'headword', label: 'Headword', required: true},
  {key: 'gloss', label: 'Gloss (English)'},
  {key: 'forms', label: 'Forms'},
  {key: 'definition', label: 'Definition (Danish)', long: true},
];

function initial(card: Card, fields: Field[]): Record<string, string> {
  const src = card as unknown as Record<string, unknown>;
  return Object.fromEntries(fields.map(f => [f.key, String(src[f.key] ?? '')]));
}

export function FixCardDrawer({
  card,
  onClose,
  onSaved,
  onDeleted,
}: {
  card: Card | null;
  onClose: () => void;
  onSaved: (patch: Partial<Card>) => void;
  onDeleted: () => void;
}) {
  const isWord = card?.word_id != null;
  const fields = !card ? [] : isWord ? WORD_FIELDS : card.kind === 'error_pattern' ? ERROR_FIELDS : ITEM_FIELDS;
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setError('');
    if (card) {
      setForm(initial(card, fields));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card]);

  const setOpen = (o: boolean) => {
    if (!o) {
      onClose();
    }
  };

  const save = async () => {
    if (!card) {
      return;
    }
    const before = initial(card, fields);
    const changed: Record<string, string | null> = {};
    for (const f of fields) {
      const now = form[f.key]?.trim() ?? '';
      if (now !== before[f.key].trim()) {
        changed[f.key] = now === '' ? null : now;
      }
    }
    if (Object.keys(changed).length === 0) {
      onClose();
      return;
    }
    try {
      if (isWord) {
        const w = await api.editWord(card.word_id as number, changed);
        onSaved({headword: w.headword, gloss: w.gloss, forms: w.forms, definition: w.definition,
          content: w.headword, answer: w.gloss});
      } else {
        const it = await api.editItem(card.item_id, changed);
        onSaved({content: it.content, answer: it.answer, description: it.description, context: it.context,
          pairs: splitPairs(it.content, it.answer)});
      }
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async () => {
    if (!card) {
      return;
    }
    setDeleting(true);
    try {
      if (isWord) {
        await api.deleteWord(card.word_id as number);
      } else {
        await api.deleteItem(card.item_id);
      }
      setConfirm(false);
      onDeleted();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setConfirm(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <Drawer isOpen={card != null} onOpenChange={setOpen} label="Fix this card" width={440} purpose="form">
        <Layout
          header={
            <DrawerHeader
              title="Fix this card"
              subtitle={isWord ? 'Changes the word everywhere it appears' : 'Changes what the card shows, not when it is due'}
              onOpenChange={setOpen}
            />
          }
          content={
            <LayoutContent>
              <VStack gap={4}>
                {error && <Banner status="error" title="Not saved" description={error} />}
                {fields.map(f =>
                  f.long ? (
                    <TextArea
                      key={f.key}
                      label={f.label}
                      value={form[f.key] ?? ''}
                      onChange={v => setForm(s => ({...s, [f.key]: v}))}
                      rows={3}
                    />
                  ) : (
                    <TextInput
                      key={f.key}
                      label={f.label}
                      description={f.description}
                      value={form[f.key] ?? ''}
                      onChange={v => setForm(s => ({...s, [f.key]: v}))}
                      isRequired={f.required}
                      width="100%"
                    />
                  ),
                )}
                <Text type="supporting" color="secondary">
                  {isWord
                    ? 'Delete removes the word, its examples, its card and the card history.'
                    : 'Delete removes this card and its review history. Use it for a card that is not a real mistake.'}
                </Text>
              </VStack>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <HStack gap={2} hAlign="between" wrap="wrap">
                <Button
                  label={isWord ? 'Delete word' : 'Delete card'}
                  variant="destructive"
                  icon={<Icon icon={TrashIcon} size="sm" />}
                  onClick={() => setConfirm(true)}
                />
                <HStack gap={2}>
                  <Button label="Cancel" onClick={onClose} />
                  <Button label="Save" variant="primary" clickAction={save} />
                </HStack>
              </HStack>
            </LayoutFooter>
          }
        />
      </Drawer>
      <AlertDialog
        isOpen={confirm}
        onOpenChange={setConfirm}
        title={isWord ? 'Delete this word?' : 'Delete this card?'}
        description="This cannot be undone."
        actionLabel="Delete"
        onAction={remove}
        isActionLoading={deleting}
      />
    </>
  );
}
