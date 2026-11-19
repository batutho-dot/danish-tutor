import {Button} from '@astryxdesign/core/Button';
import {Icon} from '@astryxdesign/core/Icon';
import {SpeakerWaveIcon} from '@heroicons/react/24/outline';
import {NO_VOICE_HELP, speakDanish, useVoice} from './speech';

export function HearIt({text, size = 'md'}: {text: string; size?: 'sm' | 'md' | 'lg'}) {
  const {name} = useVoice();
  const none = name === 'none';
  return (
    <Button
      label="Hear it"
      size={size}
      variant="secondary"
      icon={<Icon icon={SpeakerWaveIcon} size="sm" />}
      isDisabled={none || !text}
      tooltip={none ? NO_VOICE_HELP : `Read aloud (${name})`}
      onClick={() => void speakDanish(text)}
    />
  );
}
