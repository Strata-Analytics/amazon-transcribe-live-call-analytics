// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useRef } from 'react';
import { Menu } from 'lucide-react';
import 'amazon-connect-streams';

import useAppContext from '../../contexts/app';
import { cn } from '../../lib/utils';
import Navigation from '../call-analytics-layout/navigation';

const CONNECT_CCP_URL = 'https://lca-demo-strata.my.connect.aws/connect/ccp-v2';

const ConnectLayout = () => {
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const containerRef = useRef(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (initialized.current || !containerRef.current) return;
    initialized.current = true;

    window.connect.core.initCCP(containerRef.current, {
      ccpUrl: CONNECT_CCP_URL,
      loginPopup: true,
      loginPopupAutoClose: true,
      loginOptions: {
        autoClose: true,
        height: 600,
        width: 480,
      },
      softphone: {
        allowFramedSoftphone: true,
        disableRingtone: false,
      },
      pageOptions: {
        enableAudioDeviceSettings: true,
        enablePhoneTypeSettings: true,
      },
    });
  }, []);

  return (
    <div className="flex overflow-hidden bg-background" style={{ height: 'calc(100vh - 56px)' }}>
      <aside
        className={cn(
          'flex-none overflow-hidden border-r border-border bg-background transition-[width] duration-200',
          navigationOpen ? 'w-56' : 'w-0',
        )}
      >
        <Navigation />
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex-none flex items-center gap-2 border-b border-border px-4 py-2">
          <button
            onClick={() => setNavigationOpen(!navigationOpen)}
            className="rounded p-1 hover:bg-accent transition-colors"
            aria-label="Toggle navigation"
          >
            <Menu className="h-5 w-5 text-muted-foreground" />
          </button>
          <span className="text-sm font-medium text-foreground">Amazon Connect</span>
        </div>

        <div ref={containerRef} className="flex-1 w-full" />
      </div>
    </div>
  );
};

export default ConnectLayout;
