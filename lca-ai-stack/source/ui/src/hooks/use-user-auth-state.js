// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState, useEffect } from 'react';
import { Auth, Hub, Logger } from 'aws-amplify';

const logger = new Logger('useUserAuthState');

const useUserAuthState = (awsconfig) => {
  const [authState, setAuthState] = useState();
  const [user, setUser] = useState();

  useEffect(() => {
    // Check if already authenticated on mount / config change
    Auth.currentAuthenticatedUser()
      .then((u) => {
        logger.debug('already signed in', u);
        setAuthState('signedin');
        setUser(u);
      })
      .catch(() => {
        logger.debug('not signed in');
        setAuthState('signin');
      });

    const unsubscribe = Hub.listen('auth', ({ payload: { event } }) => {
      logger.debug('auth event', event);
      if (event === 'signIn') {
        Auth.currentAuthenticatedUser().then((u) => {
          setAuthState('signedin');
          setUser(u);
        });
      } else if (event === 'signOut') {
        setAuthState('signin');
        setUser(null);
      }
    });

    return unsubscribe;
  }, [awsconfig]);

  return { authState, user };
};

export default useUserAuthState;
