// The app's Astryx theme: @astryxdesign/theme-neutral, wired by hand rather than through the
// generated astryx-themes module, because that module also imports the theme's fonts.css,
// which loads the Figtree font from Google Fonts. This app makes no network calls, so the
// theme uses system fonts instead.

import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import '@astryxdesign/theme-neutral/theme.css';

export const appTheme = neutralTheme;
