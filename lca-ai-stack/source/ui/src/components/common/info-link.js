// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';

/* eslint-disable react/prop-types */
export const InfoLink = ({ id, onFollow }) => (
  <button
    type="button"
    id={id}
    onClick={onFollow}
    className="ml-1 text-xs text-primary hover:underline"
  >
    Info
  </button>
);

export default InfoLink;
