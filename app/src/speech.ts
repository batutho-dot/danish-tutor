// Speaking Danish aloud. The server's voice comes first (a local text-to-speech daemon, then
// the system voice, both through scripts/speak.py's functions); the browser's own
// speechSynthesis with a Danish voice is the fallback. Text sent to the server stays on this
// computer; the browser voice speaks locally too.

import {useEffect, useState} from 'react';
import {api} from './api';
import type {VoiceKind} from './api';

export const NO_VOICE_HELP =
  'No Danish voice found. Add a Danish voice in your system speech settings (Windows: ' +
  'Settings > Time & language > Language & region, add Danish with speech; macOS: System Settings > ' +
  'Accessibility > Spoken Content > System voice > Manage Voices), or run a local voice daemon. ' +
  'Then reload this page.';

export type VoiceName = 'Local voice' | 'Piper voice' | 'System voice' | 'Browser voice' | 'none';

function browserVoice(): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return null;
  }
  return window.speechSynthesis.getVoices().find(v => v.lang.toLowerCase().startsWith('da')) ?? null;
}

let serverVoice: Promise<VoiceKind> | null = null;

function loadServerVoice(): Promise<VoiceKind> {
  if (!serverVoice) {
    serverVoice = api.voice().then(
      v => v.voice,
      () => 'none' as VoiceKind,
    );
  }
  return serverVoice;
}

function speakInBrowser(text: string, slow: boolean, onEnd?: () => void): boolean {
  const voice = browserVoice();
  if (!voice) {
    return false;
  }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.voice = voice;
  u.lang = voice.lang;
  u.rate = slow ? 0.75 : 0.9;
  if (onEnd) {
    u.onend = onEnd;
    u.onerror = onEnd;
  }
  window.speechSynthesis.speak(u);
  return true;
}

// A rough guess of how long a line takes to say, for the "speaking" state when the server
// plays it (the server does not report when playback ends).
export function estimateSeconds(text: string, slow = false): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1.5, words / (slow ? 2 : 2.6) + 0.8);
}

// Speak Danish text. Resolves with the voice used, or 'none' when nothing could speak it.
export async function speakDanish(
  text: string,
  opts: {slow?: boolean; onEnd?: () => void} = {},
): Promise<VoiceName> {
  const clean = text.replace(/[*_`#>]/g, '').trim();
  if (!clean) {
    return 'none';
  }
  const server = await loadServerVoice();
  if (server !== 'none') {
    try {
      const r = await api.speak(clean, opts.slow ?? false);
      if (opts.onEnd) {
        window.setTimeout(opts.onEnd, estimateSeconds(clean, opts.slow) * 1000);
      }
      return r.voice === 'local' ? 'Local voice' : r.voice === 'piper' ? 'Piper voice' : 'System voice';
    } catch {
      serverVoice = Promise.resolve('none');
    }
  }
  return speakInBrowser(clean, opts.slow ?? false, opts.onEnd) ? 'Browser voice' : 'none';
}

export function stopSpeaking() {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
  void api.speakStop().catch(() => undefined);
}

// Which voice "Hear it" and the practice window will use.
export function useVoice(): {name: VoiceName; ready: boolean} {
  const [server, setServer] = useState<VoiceKind | null>(null);
  const [browser, setBrowser] = useState<boolean>(() => browserVoice() !== null);

  useEffect(() => {
    let live = true;
    void loadServerVoice().then(v => live && setServer(v));
    if (!('speechSynthesis' in window)) {
      return () => {
        live = false;
      };
    }
    const update = () => setBrowser(browserVoice() !== null);
    update();
    window.speechSynthesis.addEventListener('voiceschanged', update);
    return () => {
      live = false;
      window.speechSynthesis.removeEventListener('voiceschanged', update);
    };
  }, []);

  const name: VoiceName =
    server === 'local'
      ? 'Local voice'
      : server === 'piper'
        ? 'Piper voice'
        : server === 'system'
          ? 'System voice'
          : browser
            ? 'Browser voice'
            : 'none';
  return {name, ready: server !== null};
}
