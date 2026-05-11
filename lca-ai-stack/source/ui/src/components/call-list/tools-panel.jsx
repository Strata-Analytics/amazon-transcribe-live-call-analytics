// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';

const ToolsPanel = () => (
  <div className="px-4 py-4 text-sm space-y-2">
    <h2 className="font-semibold text-foreground">Calls</h2>
    <p className="text-muted-foreground">
      View a list of calls and related information such as phone number, initiation time, sentiment
      and duration.
    </p>
    <p className="text-muted-foreground">Use the search bar to filter on any field.</p>
    <p className="text-muted-foreground">
      To drill down even further into the details, select an individual call.
    </p>
  </div>
);

export default ToolsPanel;
