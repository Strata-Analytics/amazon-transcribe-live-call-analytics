// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';

import { CALLS_PATH } from '../../routes/constants';
import CallPanel from '../call-panel';
import { IN_PROGRESS_STATUS } from '../common/get-recording-status';

export const SPLIT_PANEL_I18NSTRINGS = {
  preferencesTitle: 'Split panel preferences',
  preferencesPositionLabel: 'Split panel position',
  preferencesPositionDescription: 'Choose the default split panel position for the service.',
  preferencesPositionSide: 'Side',
  preferencesPositionBottom: 'Bottom',
  preferencesConfirm: 'Confirm',
  preferencesCancel: 'Cancel',
  closeButtonAriaLabel: 'Close panel',
  openButtonAriaLabel: 'Open panel',
  resizeHandleAriaLabel: 'Resize split panel',
};

const EMPTY_PANEL_CONTENT = {
  header: '0 calls selected',
  body: 'Select a call to see its details.',
};

const getPanelContentSingle = ({ items, setToolsOpen, callTranscriptPerCallId }) => {
  if (!items.length) {
    return EMPTY_PANEL_CONTENT;
  }

  const item = items[0];

  return {
    header: 'Call Details',
    body: (
      <CallPanel
        item={item}
        setToolsOpen={setToolsOpen}
        callTranscriptPerCallId={callTranscriptPerCallId}
      />
    ),
  };
};

const getPanelContentMultiple = ({ items, setToolsOpen, callTranscriptPerCallId }) => {
  if (!items.length) {
    return EMPTY_PANEL_CONTENT;
  }

  if (items.length === 1) {
    return getPanelContentSingle({ items, setToolsOpen, callTranscriptPerCallId });
  }

  const liveCount = items.filter(
    ({ recordingStatusLabel }) => recordingStatusLabel === IN_PROGRESS_STATUS,
  ).length;

  return {
    header: `${items.length} calls selected`,
    body: (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">Live calls</div>
          <a href={`#${CALLS_PATH}`} className="text-2xl font-light text-primary hover:underline">
            {liveCount}
          </a>
        </div>
      </div>
    ),
  };
};

const getPanelContentComparison = ({ items }) => {
  if (!items.length) {
    return {
      header: '0 calls selected',
      body: 'Select a call to see its details. Select multiple calls to compare.',
    };
  }

  if (items.length === 1) {
    return getPanelContentSingle({ items });
  }

  const keyHeaderMap = {
    callId: 'Call ID',
    initiationTimeStamp: 'Initiation Timestamp',
  };

  const rows = ['callId', 'initiationTimeStamp'].map((key) => {
    const data = { comparisonType: keyHeaderMap[key] };
    items.forEach((item) => {
      data[item.id] = item[key];
    });
    return data;
  });

  return {
    header: `${items.length} calls selected`,
    body: (
      <div className="overflow-auto">
        <p className="text-sm font-medium text-foreground mb-3">Compare details</p>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground border-b border-border" />
              {items.map(({ id }) => (
                <th key={id} className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground border-b border-border">
                  {id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.comparisonType} className="border-b border-border">
                <td className="px-3 py-2 font-medium text-foreground">{row.comparisonType}</td>
                {items.map(({ id }) => (
                  <td key={id} className="px-3 py-2 text-muted-foreground">
                    {Array.isArray(row[id]) ? row[id].join(', ') : row[id]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
  };
};

export const getPanelContent = (items, type, setToolsOpen, callTranscriptPerCallId) => {
  if (type === 'single') {
    return getPanelContentSingle({ items, setToolsOpen, callTranscriptPerCallId });
  }
  if (type === 'multiple') {
    return getPanelContentMultiple({ items, setToolsOpen, callTranscriptPerCallId });
  }
  return getPanelContentComparison({ items });
};
