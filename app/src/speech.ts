// "Hear it": the browser's own speech synthesis with a Danish voice. Nothing is sent to the
// server. If the browser lists no voice whose language starts with "da", the button is
// disabled and its tooltip says how to add one.

import {useEffect, useState} from 'react';

export const NO_VOICE_HELP =
  'No Danish voice found. Windows: Settings > Time & language > Speech > Add voices > Danish. ' +
  'macOS: System Settings > Accessibility > Spoken Content > System voice > Manage Voices > Danish. ' +
  'Then reload this page.';

function findVoice(): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return null;
  }
  const voices = window.speechSynthesis.getVoices();
  return voices.find(v => v.lang.toLowerCase().startsWith('da')) ?? null;
}

export function useDanishVoice(): {
  voice: SpeechSynthesisVoice | null;
  speak: (text: string) => void;
} {
  const [voice, setVoice] = useState<SpeechSynthesisVoice | null>(() => findVoice());

  useEffect(() => {
    if (!('speechSynthesis' in window)) {
      return;
    }
    const update = () => setVoice(findVoice());
    update();
    window.speechSynthesis.addEventListener('voiceschanged', update);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', update);
  }, []);

  const speak = (text: string) => {
    if (!voice || !text) {
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice;
    u.lang = voice.lang;
    u.rate = 0.9;
    window.speechSynthesis.speak(u);
  };

  return {voice, speak};
}
