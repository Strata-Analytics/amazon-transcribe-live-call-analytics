// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Switch, useLocation } from 'react-router-dom';
import { PhoneCall, Radio } from 'lucide-react';

import { cn } from '../../lib/utils';
import { CALLS_PATH, DEFAULT_PATH, STREAM_AUDIO_PATH } from '../../routes/constants';

export const callsNavHeader = { text: 'Call Analytics', href: `#${DEFAULT_PATH}` };
export const callsNavItems = [
  { type: 'link', text: 'Calls', href: `#${CALLS_PATH}` },
  { type: 'link', text: 'Stream Audio', href: `#${STREAM_AUDIO_PATH}` },
];

const NavLink = ({ href, icon: Icon, children, external }) => {
  const location = useLocation();
  const isActive = location.pathname === href.replace('#', '');

  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
      >
        {Icon && <Icon className="h-4 w-4 shrink-0" />}
        {children}
      </a>
    );
  }

  return (
    <a
      href={href}
      className={cn(
        'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors',
        isActive
          ? 'bg-primary/10 text-primary font-medium'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
      )}
    >
      {Icon && <Icon className="h-4 w-4 shrink-0" />}
      {children}
    </a>
  );
};

const Navigation = () => (
  <Switch>
    <Route path={STREAM_AUDIO_PATH}>
      <nav className="h-full flex flex-col py-4 px-2 overflow-y-auto">
        <div className="mb-4 px-3">
          <a href={`#${DEFAULT_PATH}`} className="text-sm font-semibold text-foreground">
            Call Analytics
          </a>
        </div>

        <div className="space-y-0.5">
          <NavLink href={`#${CALLS_PATH}`} icon={PhoneCall}>Calls</NavLink>
          <NavLink href={`#${STREAM_AUDIO_PATH}`} icon={Radio}>Stream Audio</NavLink>
        </div>
      </nav>
    </Route>
  </Switch>
);

export default Navigation;
