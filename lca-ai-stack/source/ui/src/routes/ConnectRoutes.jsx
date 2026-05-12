// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Switch, useRouteMatch } from 'react-router-dom';

import CallAnalyticsTopNavigation from '../components/call-analytics-top-navigation';
import ConnectLayout from '../components/connect-layout/ConnectLayout';

const ConnectRoutes = () => {
  const { path } = useRouteMatch();

  return (
    <Switch>
      <Route path={path}>
        <div>
          <CallAnalyticsTopNavigation />
          <ConnectLayout />
        </div>
      </Route>
    </Switch>
  );
};

export default ConnectRoutes;
