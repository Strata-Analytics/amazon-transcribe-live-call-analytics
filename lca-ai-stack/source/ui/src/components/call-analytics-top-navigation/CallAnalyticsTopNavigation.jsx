// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useRef, useEffect } from 'react';
import { Auth, Logger } from 'aws-amplify';
import { ChevronDown, LogOut, User } from 'lucide-react';

import useAppContext from '../../contexts/app';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../ui/alert-dialog';

const logger = new Logger('TopNavigation');

const CallAnalyticsTopNavigation = () => {
  const { user } = useAppContext();
  const userId = user?.attributes?.email || 'user';
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [signOutDialogOpen, setSignOutDialogOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  async function signOut() {
    try {
      await Auth.signOut();
      logger.debug('signed out');
    } catch (error) {
      logger.error('error signing out: ', error);
    }
  }

  const handleSignOutClick = () => {
    setDropdownOpen(false);
    setSignOutDialogOpen(true);
  };

  return (
    <>
      <div id="top-navigation" className="sticky top-0 z-[1002] h-14 bg-primary flex items-center justify-between px-4">
        <div className="flex items-center gap-2.5">
          <img src="/strata-logo-white.png" alt="Strata" className="h-7" />
          <div className="w-px h-5 bg-white/30" />
          <span className="text-white/70 font-semibold text-sm tracking-wide">Copilot</span>
        </div>

        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="flex items-center gap-2 text-white text-sm hover:bg-white/10 rounded px-2 py-1.5 transition-colors"
          >
            <User className="h-4 w-4" />
            <span className="max-w-[160px] truncate">{userId}</span>
            <ChevronDown className="h-3 w-3 opacity-70" />
          </button>

          {dropdownOpen && (
            <div className="absolute right-0 top-full mt-1 w-56 bg-white rounded-md shadow-lg border border-border z-50 py-1">
              <div className="px-3 py-2 text-xs text-muted-foreground border-b border-border truncate">
                {userId}
              </div>
              <button
                onClick={handleSignOutClick}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left text-foreground"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>

      {/* AlertDialog lives outside the dropdown so it doesn't unmount when dropdown closes */}
      <AlertDialog open={signOutDialogOpen} onOpenChange={setSignOutDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Sign Out</AlertDialogTitle>
            <AlertDialogDescription>
              Sign out of the application?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={signOut}>Sign Out</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};

export default CallAnalyticsTopNavigation;
