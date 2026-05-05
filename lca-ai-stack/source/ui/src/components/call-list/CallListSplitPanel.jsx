// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect } from 'react';
import { Logger } from 'aws-amplify';

import useCallsContext from '../../contexts/calls';

import { getPanelContent } from './calls-split-panel-config';
import { IN_PROGRESS_STATUS } from '../common/get-recording-status';

const logger = new Logger('CallListSplitPanel');

const CallListSplitPanel = () => {
  const {
    callTranscriptPerCallId,
    setLiveTranscriptCallId,
    sendGetTranscriptSegmentsRequest,
    selectedItems,
    setToolsOpen,
  } = useCallsContext();

  const { header: panelHeader, body: panelBody } = getPanelContent(
    selectedItems,
    'multiple',
    setToolsOpen,
    callTranscriptPerCallId,
  );

  const sendTranscriptSegmentsRequests = async (item) => {
    const { callId } = item;
    if (!callTranscriptPerCallId[callId]) {
      await sendGetTranscriptSegmentsRequest(callId);
    }
    if (item?.recordingStatusLabel === IN_PROGRESS_STATUS) {
      setLiveTranscriptCallId(callId);
    }
  };

  useEffect(() => {
    logger.debug('selected items', selectedItems);

    if (selectedItems?.length === 1) {
      const item = selectedItems[0];
      sendTranscriptSegmentsRequests(item);
    }

    return () => {
      logger.debug('set live transcript contact to null');
      setLiveTranscriptCallId(null);
    };
  }, [selectedItems]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex-none px-4 py-2.5 border-b border-border text-sm font-medium text-foreground">
        {panelHeader}
      </div>
      <div className="flex-1 overflow-auto p-4">
        {panelBody}
      </div>
    </div>
  );
};

export default CallListSplitPanel;
