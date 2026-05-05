// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Redirect, Route, Switch } from 'react-router-dom';
import { Auth, Logger } from 'aws-amplify';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { LOGIN_PATH, LOGOUT_PATH, REDIRECT_URL_PARAM } from './constants';

const logger = new Logger('UnauthRoutes');

const LoginForm = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [challengeUser, setChallengeUser] = useState(null);

  const handleSignIn = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const u = await Auth.signIn(email, password);
      if (u.challengeName === 'NEW_PASSWORD_REQUIRED') {
        setChallengeUser(u);
      }
      logger.debug('signed in', u);
    } catch (err) {
      logger.error('sign in error', err);
      setError(err.message || 'Sign in failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleNewPassword = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await Auth.completeNewPassword(challengeUser, newPassword);
      logger.debug('new password set');
    } catch (err) {
      logger.error('new password error', err);
      setError(err.message || 'Failed to set new password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (challengeUser) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-muted/30 px-4">
        <div className="w-full max-w-sm bg-white border border-border rounded-xl p-8 shadow-xl">
          <div className="mb-6">
            <div className="flex items-center justify-center gap-3 mb-5">
              <img src="/strata-logo.png" alt="Strata" className="h-9" />
              <div className="w-px h-8 bg-border" />
              <span className="text-2xl font-semibold text-foreground/60 tracking-wide">Copilot</span>
            </div>
            <h1 className="text-base font-semibold text-foreground text-center">New password required</h1>
            <p className="mt-1 text-sm text-muted-foreground text-center">
              Please set a new password to continue.
            </p>
          </div>
          {error && (
            <div className="mb-4 rounded-md bg-destructive/10 border border-destructive/20 px-4 py-2.5 text-sm text-destructive">
              {error}
            </div>
          )}
          <form onSubmit={handleNewPassword} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm-password">Confirm password</Label>
              <Input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Saving...' : 'Set new password'}
            </Button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 px-4">
      <div className="w-full max-w-sm bg-white border border-border rounded-xl p-8 shadow-xl">
        <div className="mb-7 text-center">
          <div className="flex items-center justify-center gap-3 mb-3">
            <img src="/strata-logo.png" alt="Strata" className="h-9" />
            <div className="w-px h-8 bg-border" />
            <span className="text-2xl font-semibold text-foreground/60 tracking-wide">Copilot</span>
          </div>
          <p className="text-sm text-muted-foreground">
            Your real-time agent assist platform.<br />
            Sign in to continue.
          </p>
        </div>

        {error && (
          <div className="mb-4 rounded-md bg-destructive/10 border border-destructive/20 px-4 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}

        <form onSubmit={handleSignIn} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="you@company.com"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </div>
    </div>
  );
};

const UnauthRoutes = ({ location }) => (
  <Switch>
    <Route path={LOGIN_PATH}>
      <LoginForm />
    </Route>
    <Route path={LOGOUT_PATH}>
      <Redirect to={LOGIN_PATH} />
    </Route>
    <Route>
      <Redirect
        to={{
          pathname: LOGIN_PATH,
          search: `?${REDIRECT_URL_PARAM}=${location.pathname}${location.search}`,
        }}
      />
    </Route>
  </Switch>
);

export default UnauthRoutes;
