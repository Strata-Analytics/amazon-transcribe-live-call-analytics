// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import { Logger } from 'aws-amplify';
import { Menu, X } from 'lucide-react';

import { CallsContext } from '../../contexts/calls';

import useNotifications from '../../hooks/use-notifications';
import useCallsGraphQlApi from '../../hooks/use-calls-graphql-api';

import CallList from '../call-list';
import CallDetails from '../call-details';

import useAppContext from '../../contexts/app';
import { cn } from '../../lib/utils';

import Navigation from './navigation';
import Breadcrumbs from './breadcrumbs';
import ToolsPanel from './tools-panel';

import {
  CALL_LIST_SHARDS_PER_DAY,
  PERIODS_TO_LOAD_STORAGE_KEY,
} from '../call-list/calls-table-config';

const logger = new Logger('CallAnalyticsLayout');

const NotificationBar = ({ items }) => {
  if (!items.length) return null;
  return (
    <div className="flex-none space-y-1.5 px-4 pt-3">
      {items.map((item) => (
        <div
          key={item.id}
          className={cn(
            'flex items-center justify-between rounded-md px-4 py-2.5 text-sm border',
            item.type === 'error'
              ? 'bg-destructive/10 text-destructive border-destructive/20'
              : 'bg-primary/10 text-primary border-primary/20',
          )}
        >
          <span>{item.content}</span>
          {item.dismissible && (
            <button
              onClick={item.onDismiss}
              className="ml-4 opacity-60 hover:opacity-100 transition-opacity"
              aria-label={item.dismissLabel || 'Dismiss'}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ))}
    </div>
  );
};

const CallAnalyticsLayout = () => {
  const { navigationOpen, setNavigationOpen } = useAppContext();

  const { path } = useRouteMatch();
  logger.debug('path', path);

  const notifications = useNotifications();
  const [toolsOpen, setToolsOpen] = useState(false);

  const getInitialPeriodsToLoad = () => {
    let periods = 0.5;
    try {
      const periodsFromStorage = Math.abs(
        JSON.parse(localStorage.getItem(PERIODS_TO_LOAD_STORAGE_KEY)),
      );
      if (
        !Number.isSafeInteger(periodsFromStorage)
        || periodsFromStorage > CALL_LIST_SHARDS_PER_DAY * 30
      ) {
        logger.warn('invalid initialPeriodsToLoad value from local storage');
      } else {
        periods = (periodsFromStorage > 0) ? periodsFromStorage : periods;
        localStorage.setItem(PERIODS_TO_LOAD_STORAGE_KEY, JSON.stringify(periods));
      }
    } catch {
      logger.warn('failed to parse initialPeriodsToLoad from local storage');
    }
    return periods;
  };
  const initialPeriodsToLoad = getInitialPeriodsToLoad();

  const {
    calls,
    callTranscriptPerCallId,
    getCallDetailsFromCallIds,
    isCallsListLoading,
    periodsToLoad,
    setLiveTranscriptCallId,
    setIsCallsListLoading,
    setPeriodsToLoad,
    sendGetTranscriptSegmentsRequest,
  } = useCallsGraphQlApi({ initialPeriodsToLoad });

  // eslint-disable-next-line react/jsx-no-constructed-context-values
  const callsContextValue = {
    calls,
    callTranscriptPerCallId,
    getCallDetailsFromCallIds,
    isCallsListLoading,
    sendGetTranscriptSegmentsRequest,
    setIsCallsListLoading,
    setLiveTranscriptCallId,
    setPeriodsToLoad,
    setToolsOpen,
    periodsToLoad,
    toolsOpen,
  };

  return (
    <CallsContext.Provider value={callsContextValue}>
      <div className="flex overflow-hidden bg-background" style={{ height: 'calc(100vh - 56px)' }}>

        {/* Sidebar */}
        <aside
          className={cn(
            'flex-none overflow-hidden border-r border-border bg-background transition-[width] duration-200',
            navigationOpen ? 'w-56' : 'w-0',
          )}
        >
          <Navigation />
        </aside>

        {/* Main + Tools wrapper */}
        <div className="flex flex-1 overflow-hidden">

          {/* Main content column */}
          <div className="flex flex-1 flex-col overflow-hidden">

            {/* Header bar: nav toggle + breadcrumbs */}
            <div className="flex-none flex items-center gap-2 border-b border-border px-4 py-2">
              <button
                onClick={() => setNavigationOpen(!navigationOpen)}
                className="rounded p-1 hover:bg-accent transition-colors"
                aria-label="Toggle navigation"
              >
                <Menu className="h-5 w-5 text-muted-foreground" />
              </button>
              <Breadcrumbs />
            </div>

            {/* Notifications */}
            <NotificationBar items={notifications} />

            {/* Scrollable content */}
            <div className="flex-1 overflow-auto">
              <Switch>
                <Route exact path={path}>
                  <CallList />
                </Route>
                <Route path={`${path}/:callId`}>
                  <CallDetails />
                </Route>
              </Switch>
            </div>

          </div>

          {/* Tools panel */}
          {toolsOpen && (
            <aside className="w-72 flex-none overflow-auto border-l border-border bg-background">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
                <span className="text-sm font-medium text-foreground">Details</span>
                <button
                  onClick={() => setToolsOpen(false)}
                  className="rounded p-1 hover:bg-accent transition-colors"
                  aria-label="Close details panel"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <ToolsPanel />
            </aside>
          )}
        </div>
      </div>
    </CallsContext.Provider>
  );
};

export default CallAnalyticsLayout;
