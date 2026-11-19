import {Button} from '@astryxdesign/core/Button';
import {Icon} from '@astryxdesign/core/Icon';
import {SpeakerWaveIcon} from '@heroicons/react/24/outline';
import {NO_VOICE_HELP, useDanishVoice} from './speech';

export function HearIt({text, size = 'md'}: {text: string; size?: 'sm' | 'md' | 'lg'}) {
  const {voice, speak} = useDanishVoice();
  return (
    <Button
      label="Hear it"
      size={size}
      variant="secondary"
      icon={<Icon icon={SpeakerWaveIcon} size="sm" />}
      isDisabled={!voice || !text}
      tooltip={voice ? `Read aloud with ${voice.name}` : NO_VOICE_HELP}
      onClick={() => speak(text)}
    />
  );
}
