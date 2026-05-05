// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, Download, MoreHorizontal, RefreshCw, Settings2 } from 'lucide-react';

import { Button } from '../ui/button';
import { cn } from '../../lib/utils';
import { TableHeader } from '../common/table';
import { CALLS_PATH } from '../../routes/constants';
import { SentimentIndicator } from '../sentiment-icon/SentimentIcon';
import { SentimentTrendIndicator } from '../sentiment-trend-icon/SentimentTrendIcon';
import { CategoryAlertPill } from './CategoryAlertPill';
import { CategoryPills } from './CategoryPills';
import { getTextOnlySummary } from '../common/summary';

export const KEY_COLUMN_ID = 'callId';

/* ── Local replacements for removed Cloudscape components ─────────────── */

const statusStyles = {
  success: 'text-green-600',
  error: 'text-destructive',
  warning: 'text-yellow-600',
  'in-progress': 'text-blue-600',
  info: 'text-blue-600',
  stopped: 'text-muted-foreground',
  loading: 'text-muted-foreground',
};
const statusDots = {
  success: '●',
  error: '●',
  warning: '▲',
  'in-progress': '◐',
  info: 'ℹ',
  stopped: '■',
  loading: '○',
};
/* eslint-disable react/prop-types */
const StatusIndicator = ({ type, children }) => (
  <span className={cn('inline-flex items-center gap-1.5 text-sm', statusStyles[type] || 'text-muted-foreground')}>
    <span aria-hidden="true">{statusDots[type] || '●'}</span>
    {children}
  </span>
);

const RowMenu = ({ items }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="p-1 rounded hover:bg-accent transition-colors"
        aria-label="Row actions"
      >
        <MoreHorizontal className="h-4 w-4 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 bg-white border border-border rounded-md shadow-lg z-20 py-1 min-w-[140px]">
          {items.map((item) => (
            item.disabled ? (
              <span
                key={item.text}
                className="block px-3 py-1.5 text-sm text-muted-foreground opacity-50 cursor-not-allowed"
              >
                {item.text}
              </span>
            ) : (
              <a
                key={item.text}
                href={item.href}
                target={item.external ? '_blank' : undefined}
                rel={item.external ? 'noreferrer' : undefined}
                onClick={() => setOpen(false)}
                className="block px-3 py-1.5 text-sm hover:bg-accent text-foreground"
              >
                {item.text}
              </a>
            )
          ))}
        </div>
      )}
    </div>
  );
};

/* ── Column definitions ───────────────────────────────────────────────── */

export const COLUMN_DEFINITIONS_MAIN = [
  {
    id: KEY_COLUMN_ID,
    header: 'Call ID',
    cell: (item) => (
      <a href={`#${CALLS_PATH}/${item.callId}`} className="text-primary hover:underline text-sm">
        {item.callId}
      </a>
    ),
    sortingField: 'callId',
    width: 325,
  },
  {
    id: 'agentId',
    header: 'Agent',
    cell: (item) => item.agentId,
    sortingField: 'agentId',
  },
  {
    id: 'initiationTimeStamp',
    header: 'Initiation Timestamp',
    cell: (item) => item.initiationTimeStamp,
    sortingField: 'initiationTimeStamp',
    isDescending: false,
    width: 225,
  },
  {
    id: 'summary',
    header: 'Summary',
    cell: (item) => {
      const summary = getTextOnlySummary(item.callSummaryText);
      const preview = summary && summary.length > 20 ? `${summary.substring(0, 20)}...` : summary;
      return (
        <span title={summary ?? ''} className="cursor-help">
          {preview}
        </span>
      );
    },
    sortingField: 'summary',
  },
  {
    id: 'callerPhoneNumber',
    header: 'Caller Phone Number',
    cell: (item) => item.callerPhoneNumber,
    sortingField: 'callerPhoneNumber',
    width: 175,
  },
  {
    id: 'recordingStatus',
    header: 'Status',
    cell: (item) => (
      <StatusIndicator type={item.recordingStatusIcon}>
        {item.recordingStatusLabel}
      </StatusIndicator>
    ),
    sortingField: 'recordingStatusLabel',
    width: 150,
  },
  {
    id: 'callerSentiment',
    header: 'Caller Sentiment',
    cell: (item) => <SentimentIndicator sentiment={item?.callerSentimentLabel} />,
    sortingField: 'callerSentimentLabel',
  },
  {
    id: 'callerSentimentTrend',
    header: 'Caller Sentiment Trend',
    cell: (item) => <SentimentTrendIndicator trend={item?.callerSentimentTrendLabel} />,
    sortingField: 'callerSentimentTrendLabel',
  },
  {
    id: 'agentSentiment',
    header: 'Agent Sentiment',
    cell: (item) => <SentimentIndicator sentiment={item?.agentSentimentLabel} />,
    sortingField: 'agentSentimentLabel',
  },
  {
    id: 'agentSentimentTrend',
    header: 'Agent Sentiment Trend',
    cell: (item) => <SentimentTrendIndicator trend={item?.agentSentimentTrendLabel} />,
    sortingField: 'agentSentimentTrendLabel',
  },
  {
    id: 'conversationDuration',
    header: 'Duration',
    cell: (item) => item.conversationDurationTimeStamp,
    sortingField: 'conversationDurationTimeStamp',
  },
  {
    id: 'callCategories',
    header: 'Categories',
    cell: (item) => <CategoryPills categories={item.callCategories} />,
    sortingField: 'callCategoryCount',
    width: 200,
  },
];

export const DEFAULT_SORT_COLUMN = COLUMN_DEFINITIONS_MAIN[3];

export const SELECTION_LABELS = {
  itemSelectionLabel: (data, row) => `select ${row.callId}`,
  allItemsSelectionLabel: () => 'select all',
  selectionGroupLabel: 'Call selection',
};

const PAGE_SIZE_OPTIONS = [
  { value: 10, label: '10 Calls' },
  { value: 30, label: '30 Calls' },
  { value: 50, label: '50 Calls' },
];

const VISIBLE_CONTENT = [
  'agentId',
  'initiationTimeStamp',
  'callerPhoneNumber',
  'recordingStatus',
  'summary',
  'callerSentiment',
  'callerSentimentTrend',
  'conversationDuration',
];

export const DEFAULT_PREFERENCES = {
  pageSize: PAGE_SIZE_OPTIONS[0].value,
  visibleContent: VISIBLE_CONTENT,
  wraplines: false,
};

export const CallsPreferences = ({
  preferences,
  setPreferences,
  disabled,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
}) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(!open)}
        disabled={disabled}
        aria-label="Table preferences"
      >
        <Settings2 className="h-4 w-4" />
      </Button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-48 bg-white border border-border rounded-md shadow-lg z-20 p-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Page size
          </p>
          <select
            value={preferences.pageSize}
            onChange={(e) => setPreferences({ ...preferences, pageSize: Number(e.target.value) })}
            className="w-full text-sm border border-input rounded px-2 py-1.5 bg-background text-foreground"
          >
            {pageSizeOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
};

export const CALL_LIST_SHARDS_PER_DAY = 6;
const TIME_PERIOD_DROPDOWN_CONFIG = {
  'refresh-2h': { count: 0.5, text: '2 hrs' },
  'refresh-4h': { count: 1, text: '4 hrs' },
  'refresh-8h': { count: CALL_LIST_SHARDS_PER_DAY / 3, text: '8 hrs' },
  'refresh-1d': { count: CALL_LIST_SHARDS_PER_DAY, text: '1 day' },
  'refresh-2d': { count: 2 * CALL_LIST_SHARDS_PER_DAY, text: '2 days' },
  'refresh-1w': { count: 7 * CALL_LIST_SHARDS_PER_DAY, text: '1 week' },
  'refresh-2w': { count: 14 * CALL_LIST_SHARDS_PER_DAY, text: '2 weeks' },
  'refresh-1m': { count: 30 * CALL_LIST_SHARDS_PER_DAY, text: '30 days' },
};
const TIME_PERIOD_DROPDOWN_ITEMS = Object.keys(TIME_PERIOD_DROPDOWN_CONFIG).map((k) => ({
  id: k,
  ...TIME_PERIOD_DROPDOWN_CONFIG[k],
}));

export const PERIODS_TO_LOAD_STORAGE_KEY = 'periodsToLoad';

export const CallsCommonHeader = ({ resourceName = 'Calls', ...props }) => {
  const [timePeriodOpen, setTimePeriodOpen] = useState(false);
  const timePeriodRef = useRef(null);

  useEffect(() => {
    const close = (e) => {
      if (timePeriodRef.current && !timePeriodRef.current.contains(e.target)) {
        setTimePeriodOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const onPeriodChange = (item) => {
    props.setPeriodsToLoad(item.count);
    localStorage.setItem(PERIODS_TO_LOAD_STORAGE_KEY, JSON.stringify(item.count));
    setTimePeriodOpen(false);
  };

  const periodText = TIME_PERIOD_DROPDOWN_ITEMS.find((i) => i.count === props.periodsToLoad)?.text || '';

  return (
    <TableHeader
      title={resourceName}
      selectedItems={props.selectedItems}
      totalItems={props.totalItems}
      updateTools={props.updateTools}
      actionButtons={
        <div className="flex items-center gap-2">
          <div className="relative" ref={timePeriodRef}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setTimePeriodOpen(!timePeriodOpen)}
              disabled={props.loading}
            >
              {`Load: ${periodText}`}
              <ChevronDown className="h-3 w-3 ml-1" />
            </Button>
            {timePeriodOpen && (
              <div className="absolute left-0 top-full mt-1 bg-white border border-border rounded-md shadow-lg z-20 py-1 min-w-[110px]">
                {TIME_PERIOD_DROPDOWN_ITEMS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onPeriodChange(item)}
                    className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
                  >
                    {item.text}
                  </button>
                ))}
              </div>
            )}
          </div>

          <Button
            variant="outline"
            size="icon"
            disabled={props.loading}
            onClick={() => props.setIsLoading(true)}
            aria-label="Refresh"
          >
            <RefreshCw className={cn('h-4 w-4', props.loading && 'animate-spin')} />
          </Button>

          <Button
            variant="outline"
            size="icon"
            disabled={props.loading}
            onClick={() => props.downloadToExcel()}
            aria-label="Download"
          >
            <Download className="h-4 w-4" />
          </Button>
        </div>
      }
    />
  );
};
