// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Loader2 } from 'lucide-react';
import { useCollection } from '@cloudscape-design/collection-hooks';
import { Logger } from 'aws-amplify';

import useCallsContext from '../../contexts/calls';
import useSettingsContext from '../../contexts/settings';

import mapCallsAttributes from '../common/map-call-attributes';
import useLocalStorage from '../common/local-storage';
import { exportToExcel } from '../common/download-func';

import {
  CallsPreferences,
  CallsCommonHeader,
  COLUMN_DEFINITIONS_MAIN,
  KEY_COLUMN_ID,
  DEFAULT_PREFERENCES,
  DEFAULT_SORT_COLUMN,
} from './calls-table-config';

import { getFilterCounterText, TableEmptyState, TableNoMatchState } from '../common/table';

import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { cn } from '../../lib/utils';
import { CALLS_PATH } from '../../routes/constants';

const logger = new Logger('CallList');

const CallList = () => {
  const [callList, setCallList] = useState([]);
  const [sortState, setSortState] = useState({
    sortingColumn: DEFAULT_SORT_COLUMN,
    isDescending: true,
  });
  const { settings } = useSettingsContext();

  const {
    calls,
    isCallsListLoading,
    setIsCallsListLoading,
    setPeriodsToLoad,
    setToolsOpen,
    periodsToLoad,
  } = useCallsContext();

  const [preferences, setPreferences] = useLocalStorage('call-list-preferences', DEFAULT_PREFERENCES);

  const {
    items,
    actions,
    filteredItemsCount,
    collectionProps,
    filterProps,
    paginationProps,
  } = useCollection(callList, {
    filtering: {
      empty: <TableEmptyState resourceName="Call" />,
      noMatch: <TableNoMatchState onClearFilter={() => actions.setFiltering('')} />,
    },
    pagination: { pageSize: preferences.pageSize },
    sorting: { defaultState: { sortingColumn: DEFAULT_SORT_COLUMN, isDescending: true } },
    selection: { keepSelection: false, trackBy: KEY_COLUMN_ID },
  });

  useEffect(() => {
    if (!isCallsListLoading) {
      logger.debug('setting call list', calls);
      setCallList(mapCallsAttributes(calls, settings));
    } else {
      logger.debug('call list is loading');
    }
  }, [isCallsListLoading, calls]);

  const visibleCols = COLUMN_DEFINITIONS_MAIN.filter((col) =>
    [KEY_COLUMN_ID, ...(preferences.visibleContent || [])].includes(col.id),
  );

  const handleSort = (col) => {
    if (!col.sortingField) return;
    const isCurrentSort = sortState.sortingColumn?.sortingField === col.sortingField;
    const newIsDescending = isCurrentSort ? !sortState.isDescending : false;
    const newState = { sortingColumn: col, isDescending: newIsDescending };
    setSortState(newState);
    collectionProps.onSortingChange({ detail: newState });
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <CallsCommonHeader
        resourceName="Calls"
        selectedItems={[]}
        totalItems={callList}
        updateTools={() => setToolsOpen(true)}
        loading={isCallsListLoading}
        setIsLoading={setIsCallsListLoading}
        periodsToLoad={periodsToLoad}
        setPeriodsToLoad={setPeriodsToLoad}
        downloadToExcel={() => exportToExcel(callList, 'Call-List')}
      />

      {/* Filter + preferences bar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
        <Input
          value={filterProps.filteringText}
          onChange={(e) => filterProps.onChange({ detail: { filteringText: e.target.value } })}
          placeholder="Find calls"
          className="max-w-sm"
        />
        {filterProps.filteringText && filteredItemsCount !== undefined && (
          <span className="text-sm text-muted-foreground">
            {getFilterCounterText(filteredItemsCount)}
          </span>
        )}
        <div className="ml-auto">
          <CallsPreferences preferences={preferences} setPreferences={setPreferences} />
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {isCallsListLoading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground text-sm gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading calls...
          </div>
        ) : items.length === 0 ? (
          filterProps.filteringText
            ? <TableNoMatchState onClearFilter={() => actions.setFiltering('')} />
            : <TableEmptyState resourceName="Call" />
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 bg-background z-10 shadow-[0_1px_0_0_hsl(var(--border))]">
              <tr>
                {visibleCols.map((col) => (
                  <th
                    key={col.id}
                    style={col.width ? { width: col.width, minWidth: col.width } : undefined}
                    className={cn(
                      'px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground',
                      col.sortingField && 'cursor-pointer hover:text-foreground select-none',
                    )}
                    onClick={() => handleSort(col)}
                  >
                    <div className="flex items-center gap-1">
                      {col.header}
                      {col.sortingField
                        && sortState.sortingColumn?.sortingField === col.sortingField
                        && (sortState.isDescending
                          ? <ChevronDown className="h-3 w-3" />
                          : <ChevronUp className="h-3 w-3" />)}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item[KEY_COLUMN_ID]}
                  className="border-b border-border transition-colors cursor-pointer hover:bg-muted/40"
                  onClick={() => { window.location.hash = `${CALLS_PATH}/${item.callId}`; }}
                >
                  {visibleCols.map((col) => (
                    <td
                      key={col.id}
                      className={cn('px-4 py-3', !preferences.wraplines && 'whitespace-nowrap')}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {col.cell(item)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      <div className="flex-none flex items-center justify-between px-4 py-2.5 border-t border-border text-sm">
        <span className="text-muted-foreground">
          {`Page ${paginationProps.currentPageIndex} of ${paginationProps.pagesCount || 1}`}
        </span>
        <div className="flex items-center gap-1.5">
          <Button
            variant="outline"
            size="sm"
            disabled={paginationProps.currentPageIndex <= 1}
            onClick={() =>
              paginationProps.onChange({
                detail: { currentPageIndex: paginationProps.currentPageIndex - 1 },
              })
            }
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={
              paginationProps.currentPageIndex >= paginationProps.pagesCount
              && !paginationProps.openEnd
            }
            onClick={() =>
              paginationProps.onChange({
                detail: { currentPageIndex: paginationProps.currentPageIndex + 1 },
              })
            }
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
};

export default CallList;
