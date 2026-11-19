// Frame scaffolded from the Astryx `shell-side-nav` template: AppShell with a SideNav, which
// AppShell moves into a drawer on phones. Routing is a hash (#/review), so the server only
// ever serves index.html and its assets.

import {useEffect, useState} from 'react';
import {AppShell} from '@astryxdesign/core/AppShell';
import {Banner} from '@astryxdesign/core/Banner';
import {Divider} from '@astryxdesign/core/Divider';
import {Icon} from '@astryxdesign/core/Icon';
import {NavIcon} from '@astryxdesign/core/NavIcon';
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@astryxdesign/core/SegmentedControl';
import {
  SideNav,
  SideNavHeading,
  SideNavItem,
  SideNavSection,
} from '@astryxdesign/core/SideNav';
import {VStack} from '@astryxdesign/core/Stack';
import {Text} from '@astryxdesign/core/Text';
import {Theme} from '@astryxdesign/core/theme';
import {
  AcademicCapIcon,
  BookOpenIcon,
  CalendarDaysIcon,
  ChatBubbleLeftRightIcon,
  MicrophoneIcon,
  Squares2X2Icon,
} from '@heroicons/react/24/outline';
import {
  AcademicCapIcon as AcademicCapSolid,
  BookOpenIcon as BookOpenSolid,
  CalendarDaysIcon as CalendarDaysSolid,
  MicrophoneIcon as MicrophoneSolid,
  Squares2X2Icon as Squares2X2Solid,
} from '@heroicons/react/24/solid';
import {appTheme} from './theme';
import {DATA_CHANGED, api} from './api';
import Overview from './pages/Overview';
import Review from './pages/Review';
import WordBank from './pages/WordBank';
import Sessions from './pages/Sessions';
import Practice from './pages/Practice';

type Route = 'overview' | 'practice' | 'review' | 'words' | 'sessions';
type Mode = 'light' | 'dark' | 'system';

function readRoute(): Route {
  const h = window.location.hash.replace(/^#\/?/, '').split('/')[0];
  return h === 'practice' || h === 'review' || h === 'words' || h === 'sessions' ? h : 'overview';
}

function readMode(): Mode {
  const fromUrl = new URLSearchParams(window.location.search).get('theme');
  if (fromUrl === 'light' || fromUrl === 'dark' || fromUrl === 'system') {
    return fromUrl;
  }
  try {
    const saved = window.localStorage.getItem('dansk-theme');
    if (saved === 'light' || saved === 'dark' || saved === 'system') {
      return saved;
    }
  } catch {
    // storage blocked: fall back to the system setting
  }
  return 'system';
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);
  const [mode, setMode] = useState<Mode>(readMode);
  const [example, setExample] = useState<{on: boolean; demo: boolean; today: string}>({
    on: false,
    demo: false,
    today: '',
  });

  // Overview, Word bank and Sessions refetch when the window gets focus again or a practice
  // session saved (a new key remounts them); they also load fresh on every route change.
  const [dataKey, setDataKey] = useState(0);
  useEffect(() => {
    const bump = () => setDataKey(k => k + 1);
    window.addEventListener('focus', bump);
    window.addEventListener(DATA_CHANGED, bump);
    return () => {
      window.removeEventListener('focus', bump);
      window.removeEventListener(DATA_CHANGED, bump);
    };
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    api
      .summary()
      .then(s => setExample({on: s.example_data || s.demo, demo: s.demo, today: s.today}))
      .catch(() => setExample({on: false, demo: false, today: ''}));
  }, []);

  const changeMode = (m: string) => {
    const next = m as Mode;
    setMode(next);
    try {
      window.localStorage.setItem('dansk-theme', next);
    } catch {
      // not saved; the choice still applies until reload
    }
  };

  const nav = (
    <SideNav
      header={
        <SideNavHeading
          heading="Danish tutor"
          icon={<NavIcon icon={<Icon icon={ChatBubbleLeftRightIcon} size="sm" />} />}
          headingHref="#/"
        />
      }
      footer={
        <VStack gap={2} padding={2}>
          <Text type="supporting">Appearance</Text>
          <SegmentedControl label="Colour mode" value={mode} onChange={changeMode} size="sm" layout="fill">
            <SegmentedControlItem value="light" label="Light" />
            <SegmentedControlItem value="dark" label="Dark" />
            <SegmentedControlItem value="system" label="Auto" />
          </SegmentedControl>
        </VStack>
      }>
      <SideNavSection title="Practice" isHeaderHidden>
        <SideNavItem
          label="Overview"
          icon={Squares2X2Icon}
          selectedIcon={Squares2X2Solid}
          href="#/"
          isSelected={route === 'overview'}
        />
        <SideNavItem
          label="Practice"
          icon={MicrophoneIcon}
          selectedIcon={MicrophoneSolid}
          href="#/practice"
          isSelected={route === 'practice'}
        />
        <SideNavItem
          label="Review"
          icon={AcademicCapIcon}
          selectedIcon={AcademicCapSolid}
          href="#/review"
          isSelected={route === 'review'}
        />
      </SideNavSection>
      <Divider />
      <SideNavSection title="Library" isHeaderHidden>
        <SideNavItem
          label="Word bank"
          icon={BookOpenIcon}
          selectedIcon={BookOpenSolid}
          href="#/words"
          isSelected={route === 'words'}
        />
        <SideNavItem
          label="Sessions"
          icon={CalendarDaysIcon}
          selectedIcon={CalendarDaysSolid}
          href="#/sessions"
          isSelected={route === 'sessions'}
        />
      </SideNavSection>
    </SideNav>
  );

  return (
    <Theme theme={appTheme} mode={mode}>
      <AppShell
        contentPadding={0}
        sideNav={nav}
        banner={
          example.on ? (
            <Banner
              status="info"
              container="section"
              title="Example data"
              description={
                "You are looking at invented example data, not a real learner's record." +
                (example.demo ? ` Demo mode: today is set to ${example.today}, and changes vanish when the server stops.` : '')
              }
            />
          ) : undefined
        }>
        {route === 'overview' && <Overview key={dataKey} />}
        {route === 'practice' && <Practice />}
        {route === 'review' && <Review />}
        {route === 'words' && <WordBank key={dataKey} />}
        {route === 'sessions' && <Sessions key={dataKey} />}
      </AppShell>
    </Theme>
  );
}
