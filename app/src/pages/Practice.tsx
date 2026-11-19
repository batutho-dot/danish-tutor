// Practice: the conversation window. Frame from the Astryx `ai-chat` page template (Layout +
// LayoutContent padding 0, ChatLayout with a ChatComposer dock, ChatMessageList of
// ChatMessage / ChatMessageBubble); the mode picker uses ClickableCard tiles in a Grid.
//
// The tutor runs on the server (scripts/dansk_practice.py, the Anthropic API). This page
// long-polls its events. Hidden listening sentences arrive as their own event and are only
// played, never shown. Live corrections arrive as "fix" events and show under the learner's
// own line. Tutor replies are spoken through the voice chain (server voice first, then the
// browser's Danish voice).

import {useCallback, useEffect, useRef, useState} from 'react';
import {HStack, Layout, LayoutContent, StackItem, VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {
  ChatComposer,
  ChatComposerInput,
  ChatLayout,
  ChatMessage,
  ChatMessageBubble,
  ChatMessageList,
  ChatMessageMetadata,
  ChatSystemMessage,
  useChatDictation,
} from '@astryxdesign/core/Chat';
import type {ChatComposerInputHandle} from '@astryxdesign/core/Chat';
import {Avatar} from '@astryxdesign/core/Avatar';
import {Badge} from '@astryxdesign/core/Badge';
import {Banner} from '@astryxdesign/core/Banner';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {ClickableCard} from '@astryxdesign/core/ClickableCard';
import {Grid} from '@astryxdesign/core/Grid';
import {Icon} from '@astryxdesign/core/Icon';
import {Selector} from '@astryxdesign/core/Selector';
import {Spinner} from '@astryxdesign/core/Spinner';
import {StatusDot} from '@astryxdesign/core/StatusDot';
import {Switch} from '@astryxdesign/core/Switch';
import {TextInput} from '@astryxdesign/core/TextInput';
import {
  AcademicCapIcon,
  ArrowPathIcon,
  BookOpenIcon,
  ChatBubbleLeftRightIcon,
  ClockIcon,
  EyeIcon,
  MicrophoneIcon,
  SpeakerWaveIcon,
  StopIcon,
} from '@heroicons/react/24/outline';
import {announceDataChanged, api, stopPracticeOnUnload} from '../api';
import type {PracticeEvent, PracticeSnapshot, PracticeStatus} from '../api';
import {speakDanish, stopSpeaking, useVoice} from '../speech';

// ============= SETTINGS KEPT PER BROWSER =============

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === '1';
  } catch {
    return fallback;
  }
}

function writeFlag(key: string, value: boolean) {
  try {
    window.localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // not kept; the choice still applies until reload
  }
}

function usePersistentFlag(key: string, fallback: boolean): [boolean, (v: boolean) => void] {
  const [v, setV] = useState(() => readFlag(key, fallback));
  return [
    v,
    (next: boolean) => {
      setV(next);
      writeFlag(key, next);
    },
  ];
}

// ============= MODES =============

const MODES = [
  {id: 'chat', title: 'Speaking', note: 'A relaxed 15 minute chat. Small corrections appear as you go.', icon: ChatBubbleLeftRightIcon},
  {id: 'short', title: 'Short chat', note: 'The same, in about 5 minutes.', icon: ClockIcon},
  {id: 'listen', title: 'Listening drill', note: 'Hear a sentence, say what you understood. Nothing is shown first.', icon: SpeakerWaveIcon},
  {id: 'words', title: 'Learn 10 new words', note: 'On a topic you pick, or one chosen for you. Saved as cards for tomorrow.', icon: BookOpenIcon},
] as const;

type ModeId = (typeof MODES)[number]['id'];

function modeFromHash(): ModeId | null {
  const m = window.location.hash.match(/^#\/practice\/(chat|short|listen|words)$/);
  return m ? (m[1] as ModeId) : null;
}

// ============= CONVERSATION MODEL =============

type Fix = {said: string; correct: string; why: string};
type Line = {
  id: number;
  role: 'tutor' | 'learner' | 'note';
  text: string;
  open?: boolean; // tutor line still streaming
  fixes?: Fix[];
  listening?: boolean; // this tutor turn played a hidden sentence
  heard?: string; // that sentence, shown once the learner has answered
  revealed?: boolean;
  tone?: 'saved' | 'error';
};

const SIGNAL_LABEL: Record<string, string> = {
  your_turn: 'Your turn',
  listening: 'Listening',
  replay: 'Listening again',
  saving: 'Saving',
  done: 'Done',
};

function chipFor(signal: {signal: string; detail: string} | null, state: PracticeSnapshot['state'] | null, speaking: boolean) {
  if (state === 'starting' || state === 'replying') {
    return {label: 'Tutor is thinking', variant: 'neutral' as const, dot: 'accent' as const};
  }
  if (speaking) {
    return {label: 'Speaking', variant: 'info' as const, dot: 'accent' as const};
  }
  if (state === 'finished' || signal?.signal === 'done') {
    return {label: 'Done', variant: 'success' as const, dot: 'success' as const};
  }
  if (state === 'ended') {
    return {label: 'Stopped', variant: 'neutral' as const, dot: 'neutral' as const};
  }
  if (!signal) {
    return {label: 'Your turn', variant: 'success' as const, dot: 'success' as const};
  }
  const label = SIGNAL_LABEL[signal.signal] ?? 'Your turn';
  return {
    label: signal.detail ? `${label} ${signal.detail}` : label,
    variant: signal.signal === 'saving' ? ('warning' as const) : ('success' as const),
    dot: signal.signal === 'saving' ? ('warning' as const) : ('success' as const),
  };
}

// ============= MODE PICKER =============

function Picker({
  status,
  voice,
  onStart,
  busy,
  error,
}: {
  status: PracticeStatus | null;
  voice: string;
  onStart: (mode: ModeId, topic?: string) => void;
  busy: boolean;
  error: string;
}) {
  const [wordsOpen, setWordsOpen] = useState(modeFromHash() === 'words');
  const [topic, setTopic] = useState('');
  const ready = status?.available ?? false;
  return (
    <VStack gap={6}>
      <VStack gap={1}>
        <Heading level={1}>Practice</Heading>
        <Text color="secondary">
          Talk with your tutor by voice or by typing. Voice: {voice === 'none' ? 'none found (replies are text only)' : voice}.
        </Text>
      </VStack>
      {status && !status.available && (
        <Banner
          status="warning"
          title={status.problem === 'sdk' ? 'One step left: install the Anthropic SDK' : 'The tutor needs an Anthropic API key'}
          description={status.message}
        />
      )}
      {error && <Banner status="error" title="Could not start" description={error} />}
      {!status ? (
        <Spinner label="Loading" />
      ) : wordsOpen ? (
        <Card>
          <VStack gap={4} padding={2}>
            <Heading level={3}>Learn 10 new words</Heading>
            <Text color="secondary">Pick a topic, or let the tutor choose one that fits your goal ({status.goal}).</Text>
            <TextInput
              label="Your topic"
              value={topic}
              onChange={setTopic}
              placeholder="For example: at the doctor"
              width="100%"
              onEnter={() => topic.trim() && onStart('words', topic.trim())}
            />
            <HStack gap={2} wrap="wrap">
              {status.topics.map(t => (
                <Button key={t} label={t} size="sm" variant="secondary" onClick={() => setTopic(t)} />
              ))}
            </HStack>
            <HStack gap={2} wrap="wrap">
              <Button
                label="Start with this topic"
                variant="primary"
                isDisabled={!ready || !topic.trim()}
                isLoading={busy}
                onClick={() => onStart('words', topic.trim())}
              />
              <Button label="Choose for me" isDisabled={!ready} isLoading={busy} onClick={() => onStart('words')} />
              <Button label="Back" variant="ghost" onClick={() => setWordsOpen(false)} />
            </HStack>
          </VStack>
        </Card>
      ) : (
        <Grid columns={{minWidth: 240, repeat: 'fit'}} gap={4}>
          {MODES.map(m => (
            <ClickableCard
              key={m.id}
              label={m.title}
              isDisabled={!ready || busy}
              elevation="low"
              onClick={() => (m.id === 'words' ? setWordsOpen(true) : onStart(m.id))}>
              <VStack gap={2}>
                <Icon icon={m.icon} size="lg" color="accent" />
                <Heading level={3}>{m.title}</Heading>
                <Text color="secondary">{m.note}</Text>
              </VStack>
            </ClickableCard>
          ))}
        </Grid>
      )}
    </VStack>
  );
}

// ============= CONVERSATION WINDOW =============

function Conversation({session, onClose}: {session: PracticeSnapshot; onClose: () => void}) {
  const [lines, setLines] = useState<Line[]>([]);
  const [state, setState] = useState<PracticeSnapshot['state']>(session.state);
  const [signal, setSignal] = useState<{signal: string; detail: string} | null>(null);
  const [saveError, setSaveError] = useState<{problems: string[]; path: string | null} | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const [listenSentence, setListenSentence] = useState<string | null>(null);
  const [replayed, setReplayed] = useState(false);
  const [showText, setShowText] = usePersistentFlag('dansk-show-tutor-text', true);
  const [readAloud, setReadAloud] = usePersistentFlag('dansk-read-aloud', true);
  const [autoSend, setAutoSend] = usePersistentFlag('dansk-auto-send', false);
  const [autoSeconds, setAutoSeconds] = useState('3');
  const nextId = useRef(1);
  const seq = useRef(0);
  const viaVoice = useRef(false);
  const sendAfterStop = useRef(false);
  const inputRef = useRef<ChatComposerInputHandle>(null);
  const readAloudRef = useRef(readAloud);
  useEffect(() => {
    readAloudRef.current = readAloud;
  }, [readAloud]);
  const turnSignal = useRef<string | null>(null);
  const turnListen = useRef(false);
  const turnText = useRef('');
  const listenRef = useRef<string | null>(null);

  const busy = state === 'starting' || state === 'replying';
  const over = state === 'finished' || state === 'ended';

  const say = useCallback((id: number, text: string, slow = false) => {
    setSpeakingId(id);
    void speakDanish(text, {slow, onEnd: () => setSpeakingId(cur => (cur === id ? null : cur))}).then(v => {
      if (v === 'none') {
        setSpeakingId(null);
      }
    });
  }, []);

  const playSentence = useCallback((sentence: string, slow: boolean) => {
    setSpeakingId(-1);
    void speakDanish(sentence, {slow, onEnd: () => setSpeakingId(cur => (cur === -1 ? null : cur))}).then(v => {
      if (v === 'none') {
        setSpeakingId(null);
        setError('No Danish voice could play the listening sentence. Add a Danish voice, or ask the tutor to skip it.');
      }
    });
  }, []);

  const handle = useCallback(
    (ev: PracticeEvent) => {
      switch (ev.type) {
        case 'user':
          setLines(ls => [...ls, {id: nextId.current++, role: 'learner', text: ev.text}]);
          break;
        case 'text':
          turnText.current += ev.text;
          setLines(ls => {
            const last = ls[ls.length - 1];
            if (last && last.role === 'tutor' && last.open) {
              return [...ls.slice(0, -1), {...last, text: last.text + ev.text}];
            }
            return [...ls, {id: nextId.current++, role: 'tutor', text: ev.text.replace(/^\s+/, ''), open: true}];
          });
          break;
        case 'fix':
          setLines(ls => {
            const idx = ls.map(l => l.role).lastIndexOf('learner');
            if (idx < 0) {
              return ls;
            }
            const l = ls[idx];
            return [...ls.slice(0, idx), {...l, fixes: [...(l.fixes ?? []), {said: ev.said, correct: ev.correct, why: ev.why}]}, ...ls.slice(idx + 1)];
          });
          break;
        case 'listen':
          turnListen.current = true;
          listenRef.current = ev.sentence;
          setListenSentence(ev.sentence);
          setReplayed(false);
          setLines(ls => {
            const last = ls[ls.length - 1];
            if (last && last.role === 'tutor' && last.open) {
              return [...ls.slice(0, -1), {...last, listening: true}];
            }
            return [...ls, {id: nextId.current++, role: 'tutor', text: '', open: true, listening: true}];
          });
          break;
        case 'signal':
          turnSignal.current = ev.signal;
          setSignal({signal: ev.signal, detail: ev.detail});
          break;
        case 'turn_end': {
          const sig = turnSignal.current;
          const listened = turnListen.current;
          const text = turnText.current.trim();
          turnSignal.current = null;
          turnListen.current = false;
          turnText.current = '';
          const id = nextId.current - 1;
          setLines(ls => {
            const last = ls[ls.length - 1];
            if (!last || last.role !== 'tutor' || !last.open) {
              return ls;
            }
            return [...ls.slice(0, -1), {...last, open: false, text: last.text.trim()}];
          });
          if (listened && listenRef.current) {
            playSentence(listenRef.current, false);      // the hidden sentence; the line stays quiet
          } else if (readAloudRef.current && sig !== 'saving' && text) {
            say(id, text);
          }
          window.setTimeout(() => inputRef.current?.focus(), 0);
          break;
        }
        case 'discard':
          turnText.current = '';
          setLines(ls => {
            const last = ls[ls.length - 1];
            return last && last.role === 'tutor' && last.open ? ls.slice(0, -1) : ls;
          });
          break;
        case 'saved':
          setSaveError(null);
          setLines(ls => [...ls, {id: nextId.current++, role: 'note', text: ev.line, tone: 'saved'}]);
          announceDataChanged();
          break;
        case 'save_error':
          setSaveError({problems: ev.problems, path: ev.path});
          break;
        case 'error':
          setError(ev.message);
          break;
        case 'state':
          setState(ev.state);
          break;
      }
    },
    [say, playSentence],
  );

  // Long-poll the server for events until the session is over.
  useEffect(() => {
    let live = true;
    const loop = async () => {
      while (live) {
        try {
          const r = await api.practiceEvents(session.id, seq.current);
          for (const ev of r.events) {
            seq.current = ev.seq;
            handle(ev);
          }
          setState(r.session.state);
          if (r.session.state === 'finished' || r.session.state === 'ended') {
            if (r.events.length === 0) {
              return;
            }
          }
        } catch (e) {
          if (!live) {
            return;
          }
          setError(e instanceof Error ? e.message : String(e));
          await new Promise(res => window.setTimeout(res, 1500));
        }
      }
    };
    void loop();
    return () => {
      live = false;
    };
  }, [session.id, handle]);

  // Closing the tab stops the session (the server's watchdog would too, after a while).
  useEffect(() => {
    const onHide = () => stopPracticeOnUnload(session.id);
    window.addEventListener('pagehide', onHide);
    return () => window.removeEventListener('pagehide', onHide);
  }, [session.id]);

  const send = useCallback(
    async (text: string) => {
      const t = text.trim();
      if (!t || busy || over) {
        return;
      }
      const via = viaVoice.current ? 'voice' : 'typed';
      viaVoice.current = false;
      setDraft('');
      setError('');
      stopSpeaking();
      const sentence = listenRef.current;
      if (sentence) {
        // Answered: the hidden sentence may now be shown on the line that played it.
        setLines(ls => {
          const i = ls.map(l => l.listening && !l.heard).lastIndexOf(true);
          return i < 0 ? ls : ls.map((l, j) => (j === i ? {...l, heard: sentence} : l));
        });
      }
      setListenSentence(null);
      listenRef.current = null;
      try {
        await api.practiceSend(session.id, t, via);
        setState('replying');
      } catch (e) {
        setDraft(t);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [busy, over, session.id],
  );

  const dictation = useChatDictation({
    lang: 'da-DK',
    inputRef,
    onStart: () => {
      viaVoice.current = true;
      stopSpeaking();
    },
    onEnd: () => {
      if (sendAfterStop.current) {
        sendAfterStop.current = false;
        const v = inputRef.current?.getValue() ?? '';
        window.setTimeout(() => void send(v), 0);
      }
    },
    onError: e => setError(`Speech recognition: ${e.message ?? e.error}`),
  });

  const toggleMic = useCallback(() => {
    if (dictation.isListening) {
      sendAfterStop.current = true;
      dictation.stop();
    } else if (!busy && !over) {
      dictation.start();
    }
  }, [dictation, busy, over]);

  // Hold Space (outside the text box) to talk; release to send.
  useEffect(() => {
    const isTyping = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable || el.tagName === 'BUTTON');
    };
    const down = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat && !isTyping(e.target) && dictation.isSupported && !dictation.isListening && !busy && !over) {
        e.preventDefault();
        dictation.start();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !isTyping(e.target) && dictation.isListening) {
        e.preventDefault();
        sendAfterStop.current = true;
        dictation.stop();
      }
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [dictation, busy, over]);

  // Optional: send after a pause in typing (for dictation tools that type into the box).
  useEffect(() => {
    if (!autoSend || !draft.trim() || busy || over || dictation.isListening) {
      return;
    }
    const t = window.setTimeout(() => void send(draft), Number(autoSeconds) * 1000);
    return () => window.clearTimeout(t);
  }, [autoSend, autoSeconds, draft, busy, over, send, dictation.isListening]);

  const action = async (a: 'end' | 'retry' | 'stop') => {
    setError('');
    try {
      await api.practiceAction(session.id, a);
      if (a === 'stop') {
        stopSpeaking();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const chip = chipFor(signal, state, speakingId !== null);
  const reveal = (id: number) => setLines(ls => ls.map(l => (l.id === id ? {...l, revealed: true} : l)));

  const composer = (
    <VStack gap={3}>
      {listenSentence && !over && (
        <HStack gap={2} hAlign="center" wrap="wrap">
          <Button
            label="Play the sentence again"
            size="sm"
            icon={<Icon icon={ArrowPathIcon} size="sm" />}
            onClick={() => playSentence(listenSentence, false)}
          />
          <Button
            label={replayed ? 'Slower replay used' : 'Replay slower (once)'}
            size="sm"
            isDisabled={replayed}
            onClick={() => {
              setReplayed(true);
              playSentence(listenSentence, true);
            }}
          />
        </HStack>
      )}
      {dictation.isSupported && (
        <VStack gap={1} hAlign="center">
          <Button
            label={dictation.isListening ? 'Stop and send' : 'Talk'}
            variant={dictation.isListening ? 'destructive' : 'primary'}
            size="lg"
            icon={<Icon icon={dictation.isListening ? StopIcon : MicrophoneIcon} size="md" />}
            isDisabled={(busy || over) && !dictation.isListening}
            tooltip="Click to talk, click again to send. Or hold Space."
            onClick={toggleMic}
          />
          <Text type="supporting" color="secondary" justify="center">
            {dictation.isListening ? 'Listening in Danish. Click again or release Space to send.' : 'Click to talk, or hold Space.'}
          </Text>
        </VStack>
      )}
      <ChatComposer
        value={draft}
        onChange={setDraft}
        onSubmit={v => void send(v)}
        isDisabled={over}
        placeholder={busy ? 'The tutor is replying...' : 'Skriv på dansk, or dictate into this box'}
        input={<ChatComposerInput handleRef={inputRef} label="Your answer" hasHistory={false} pasteAsToken={false} />}
        status={error ? {type: 'error', message: error} : undefined}
      />
    </VStack>
  );

  return (
    <VStack height="100%">
      <VStack gap={3} padding={4}>
        <HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <HStack gap={2} vAlign="center" wrap="wrap">
              <Heading level={2}>{MODES.find(m => m.id === session.mode)?.title ?? 'Practice'}</Heading>
              <Badge label={chip.label} variant={chip.variant} icon={<StatusDot variant={chip.dot} label={chip.label} isPulsing={busy || speakingId !== null} />} />
            </HStack>
          </StackItem>
          {speakingId !== null && (
            <Button label="Stop speaking" size="sm" icon={<Icon icon={StopIcon} size="sm" />} onClick={() => {
              stopSpeaking();
              setSpeakingId(null);
            }} />
          )}
          {!over ? (
            <>
              <Button label="End session" variant="primary" size="sm" isDisabled={busy || state === 'saved'} clickAction={() => action('end')} />
              <Button label="Stop" variant="ghost" size="sm" clickAction={() => action('stop')} />
            </>
          ) : (
            <Button label="New session" variant="primary" size="sm" onClick={onClose} />
          )}
        </HStack>
        <HStack gap={4} wrap="wrap" vAlign="center">
          <Switch label="Show tutor text" value={showText} onChange={setShowText} size="sm" />
          <Switch label="Read replies aloud" value={readAloud} onChange={setReadAloud} size="sm" />
          <Switch label="Send after a pause" value={autoSend} onChange={setAutoSend} size="sm" />
          {autoSend && (
            <Selector
              label="Pause before sending"
              isLabelHidden
              size="sm"
              value={autoSeconds}
              onChange={v => setAutoSeconds(v ?? '3')}
              options={[
                {value: '2', label: 'after 2 s'},
                {value: '3', label: 'after 3 s'},
                {value: '5', label: 'after 5 s'},
              ]}
            />
          )}
        </HStack>
        {saveError && (
          <Banner
            status="error"
            title="The session was not saved yet"
            description={saveError.problems.join(' ') + (saveError.path ? ` The payload is kept in ${saveError.path}.` : '')}
            endContent={<Button label="Try saving again" size="sm" isDisabled={busy} clickAction={() => action('retry')} />}
          />
        )}
      </VStack>
      <StackItem size="fill">
        <ChatLayout density="balanced" composer={over ? <Text color="secondary" justify="center">This session is over. Start a new one from the button above.</Text> : composer}>
          <ChatMessageList isStreaming={busy}>
            {lines.map(l => {
              if (l.role === 'note') {
                return (
                  <ChatSystemMessage key={l.id} icon={<Icon icon={AcademicCapIcon} size="sm" />}>
                    {l.text}
                  </ChatSystemMessage>
                );
              }
              if (l.role === 'learner') {
                return (
                  <ChatMessage key={l.id} sender="user">
                    <ChatMessageBubble>{l.text}</ChatMessageBubble>
                    {(l.fixes ?? []).map((f, i) => (
                      <ChatMessageBubble key={i} variant="ghost">
                        <Card variant="yellow" padding={2}>
                          <VStack gap={0.5}>
                            <Text type="supporting">
                              Small fix: <Text type="supporting" hasStrikethrough>{f.said}</Text> {'>'}{' '}
                              <Text type="supporting" weight="semibold">{f.correct}</Text>
                            </Text>
                            {f.why && (
                              <Text type="supporting" color="secondary">
                                {f.why}
                              </Text>
                            )}
                          </VStack>
                        </Card>
                      </ChatMessageBubble>
                    ))}
                  </ChatMessage>
                );
              }
              const hidden = !showText && !l.revealed;
              const speaking = speakingId === l.id;
              return (
                <ChatMessage key={l.id} sender="assistant" avatar={<Avatar name="Tutor" size="md" status={speaking ? <StatusDot variant="accent" label="Speaking" isPulsing /> : undefined} />}>
                  <ChatMessageBubble
                    variant="ghost"
                    metadata={
                      l.open ? undefined : (
                        <ChatMessageMetadata
                          footer={
                            <HStack gap={1} wrap="wrap">
                              {l.text && (
                                <Button
                                  label={speaking ? 'Speaking' : 'Replay'}
                                  variant="ghost"
                                  size="sm"
                                  icon={<Icon icon={SpeakerWaveIcon} size="sm" />}
                                  onClick={() => say(l.id, l.text)}
                                />
                              )}
                              {hidden && l.text && (
                                <Button label="Reveal this line" variant="ghost" size="sm" icon={<Icon icon={EyeIcon} size="sm" />} onClick={() => reveal(l.id)} />
                              )}
                            </HStack>
                          }
                        />
                      )
                    }>
                    {hidden ? (
                      <Text color="secondary">{l.open ? 'The tutor is talking...' : l.listening ? 'Listen to the sentence, then say what you heard.' : 'Tutor line (hidden, listen to it)'}</Text>
                    ) : (
                      <VStack gap={1}>
                        {l.text ? <Text>{l.text}</Text> : null}
                        {l.listening && !l.heard && (
                          <Text type="supporting" color="secondary">
                            A sentence is playing. Say what you heard; it is shown only after you answer.
                          </Text>
                        )}
                        {l.heard && (
                          <Text type="supporting" color="secondary">
                            The sentence was: <Text type="supporting" weight="semibold">{l.heard}</Text>
                          </Text>
                        )}
                      </VStack>
                    )}
                  </ChatMessageBubble>
                </ChatMessage>
              );
            })}
          </ChatMessageList>
        </ChatLayout>
      </StackItem>
    </VStack>
  );
}

// ============= PAGE =============

export default function Practice() {
  const [status, setStatus] = useState<PracticeStatus | null>(null);
  const [session, setSession] = useState<PracticeSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const {name: voice} = useVoice();
  const autoStarted = useRef(false);

  const load = useCallback(() => {
    api.practice().then(
      s => {
        setStatus(s);
        if (s.session && (s.session.state === 'waiting' || s.session.state === 'replying' || s.session.state === 'saved')) {
          setSession(cur => cur ?? s.session);
        }
      },
      e => setError(String(e.message ?? e)),
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const start = useCallback(async (mode: ModeId, topic?: string) => {
    setBusy(true);
    setError('');
    try {
      setSession(await api.practiceStart(mode, topic));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  // #/practice/<mode> from the Overview's buttons starts that mode (words opens the topic step).
  useEffect(() => {
    const m = modeFromHash();
    if (status?.available && m && m !== 'words' && !session && !autoStarted.current) {
      autoStarted.current = true;
      window.history.replaceState(null, '', '#/practice');
      void start(m);
    }
  }, [status, session, start]);

  return (
    <Layout
      height="fill"
      content={
        <LayoutContent padding={0}>
          {session ? (
            <Conversation
              key={session.id}
              session={session}
              onClose={() => {
                setSession(null);
                load();
              }}
            />
          ) : (
            <VStack padding={6} gap={6}>
              <Picker status={status} voice={voice} onStart={(m, t) => void start(m, t)} busy={busy} error={error} />
              <Text type="supporting" color="secondary">
                Your conversation goes to the Anthropic API under your own key. The Talk button uses your browser's speech
                recognition, which may send the audio to the browser maker's service; typing or another dictation tool works too.
              </Text>
            </VStack>
          )}
        </LayoutContent>
      }
    />
  );
}
