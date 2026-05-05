// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { useParams } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

import { CALLS_PATH } from '../../routes/constants';
import { callListBreadcrumbItems } from '../call-list/breadcrumbs';

const Breadcrumbs = () => {
  const { callId } = useParams();
  const items = [
    ...callListBreadcrumbItems,
    { text: callId, href: `#${CALLS_PATH}/${callId}` },
  ];

  return (
    <nav aria-label="Breadcrumbs">
      <ol className="flex items-center gap-1 text-sm">
        {items.map((item, i) => (
          // eslint-disable-next-line react/no-array-index-key
          <React.Fragment key={i}>
            {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
            {i < items.length - 1 ? (
              <a href={item.href} className="text-muted-foreground hover:text-foreground transition-colors">
                {item.text}
              </a>
            ) : (
              <span className="font-medium text-foreground truncate max-w-[240px]">{item.text}</span>
            )}
          </React.Fragment>
        ))}
      </ol>
    </nav>
  );
};

export default Breadcrumbs;
