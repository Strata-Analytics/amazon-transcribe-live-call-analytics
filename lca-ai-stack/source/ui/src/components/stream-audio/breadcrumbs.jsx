// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { ChevronRight } from 'lucide-react';

import { STREAM_AUDIO_PATH, DEFAULT_PATH } from '../../routes/constants';

export const callListBreadcrumbItems = [
  { text: 'Call Analytics', href: `#${DEFAULT_PATH}` },
  { text: 'Stream Audio', href: `#${STREAM_AUDIO_PATH}` },
];

const Breadcrumbs = () => (
  <nav aria-label="Breadcrumbs">
    <ol className="flex items-center gap-1 text-sm">
      {callListBreadcrumbItems.map((item, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <React.Fragment key={i}>
          {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
          {i < callListBreadcrumbItems.length - 1 ? (
            <a href={item.href} className="text-muted-foreground hover:text-foreground transition-colors">
              {item.text}
            </a>
          ) : (
            <span className="font-medium text-foreground">{item.text}</span>
          )}
        </React.Fragment>
      ))}
    </ol>
  </nav>
);

export default Breadcrumbs;
