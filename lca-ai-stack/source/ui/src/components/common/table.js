// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Info } from 'lucide-react';

import { Button } from '../ui/button';

export const getFilterCounterText = (count) => `${count} ${count === 1 ? 'match' : 'matches'}`;

const getHeaderCounterText = (items = [], selectedItems = []) => (
  selectedItems && selectedItems.length > 0
    ? `(${selectedItems.length}/${items.length})`
    : `(${items.length})`
);

const getCounter = (props) => {
  if (props.counter) return props.counter;
  if (!props.totalItems) return null;
  return getHeaderCounterText(props.totalItems, props.selectedItems);
};

/* eslint-disable react/prop-types */
export const TableHeader = (props) => (
  <div className="flex items-center justify-between px-4 py-3 border-b border-border">
    <div className="flex items-center gap-2">
      <h2 className="text-base font-semibold text-foreground">{props.title}</h2>
      {getCounter(props) && (
        <span className="text-sm text-muted-foreground">{getCounter(props)}</span>
      )}
      {props.updateTools && (
        <button
          type="button"
          onClick={props.updateTools}
          className="text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Show info"
        >
          <Info className="h-4 w-4" />
        </button>
      )}
    </div>
    {props.actionButtons && (
      <div className="flex items-center gap-2">{props.actionButtons}</div>
    )}
  </div>
);

export const TableEmptyState = ({ resourceName }) => (
  <div className="flex flex-col items-center justify-center py-16 text-center">
    <p className="font-semibold text-foreground">No {resourceName.toLowerCase()}s</p>
    <p className="mt-1 text-sm text-muted-foreground">
      No {resourceName.toLowerCase()}s found.
    </p>
  </div>
);

export const TableNoMatchState = ({ onClearFilter }) => (
  <div className="flex flex-col items-center justify-center py-16 text-center">
    <p className="font-semibold text-foreground">No matches</p>
    <p className="mt-1 mb-4 text-sm text-muted-foreground">We can&apos;t find a match.</p>
    <Button variant="outline" size="sm" onClick={onClearFilter}>
      Clear filter
    </Button>
  </div>
);
