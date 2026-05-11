// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Logger } from 'aws-amplify';
import { getWeightedSentimentLabel } from '../common/sentiment';

const logger = new Logger('SentimentCharts');

const EmptyChart = ({ title }) => (
  <div className="flex items-center justify-center h-20 rounded border border-border bg-muted/20 text-sm text-muted-foreground">
    {title} — no data available
  </div>
);

const SimpleLineChart = ({ title, series, yDomain, xTitle, yTitle, height }) => {
  const allEmpty = series.every((s) => !s.data || s.data.length <= 1);
  if (allEmpty) {
    return <EmptyChart title={title || yTitle} />;
  }

  const chartHeight = parseInt(height, 10) || 80;
  const [yMin, yMax] = yDomain || [-1, 1];
  const padding = { top: 8, right: 12, bottom: 24, left: 40 };
  const width = 400;
  const innerW = width - padding.left - padding.right;
  const innerH = chartHeight - padding.top - padding.bottom;

  const colors = ['#1007a0', '#e67e22', '#27ae60', '#e74c3c'];

  const toX = (date, xMin, xMax) => {
    if (xMax === xMin) return padding.left;
    return padding.left + ((date - xMin) / (xMax - xMin)) * innerW;
  };
  const toY = (val) => {
    const clamped = Math.max(yMin, Math.min(yMax, val));
    return padding.top + ((yMax - clamped) / (yMax - yMin)) * innerH;
  };

  const allDates = series.flatMap((s) => s.data.map((d) => d.x));
  const xMin = allDates.length ? Math.min(...allDates) : 0;
  const xMax = allDates.length ? Math.max(...allDates) : 1;

  const buildPath = (data) => {
    const pts = data.map((d) => `${toX(d.x, xMin, xMax).toFixed(1)},${toY(d.y).toFixed(1)}`);
    return `M ${pts.join(' L ')}`;
  };

  return (
    <div className="text-xs text-muted-foreground">
      {yTitle && <div className="mb-1 font-medium">{yTitle}</div>}
      <svg
        viewBox={`0 0 ${width} ${chartHeight}`}
        className="w-full overflow-visible"
        style={{ height: chartHeight }}
      >
        {/* zero line */}
        <line
          x1={padding.left}
          y1={toY(0)}
          x2={padding.left + innerW}
          y2={toY(0)}
          stroke="hsl(var(--border))"
          strokeDasharray="4 2"
          strokeWidth={1}
        />
        {series.map((s, i) => (
          s.data && s.data.length > 1 && (
            <path
              key={s.title}
              d={buildPath(s.data)}
              fill="none"
              stroke={colors[i % colors.length]}
              strokeWidth={1.5}
            />
          )
        ))}
        {/* y-axis labels */}
        <text x={padding.left - 4} y={padding.top + 4} textAnchor="end" fontSize={9} fill="currentColor">{yMax}</text>
        <text x={padding.left - 4} y={padding.top + innerH + 4} textAnchor="end" fontSize={9} fill="currentColor">{yMin}</text>
        {/* x-axis label */}
        {xTitle && (
          <text
            x={padding.left + innerW / 2}
            y={chartHeight - 2}
            textAnchor="middle"
            fontSize={9}
            fill="currentColor"
          >
            {xTitle}
          </text>
        )}
      </svg>
      {/* Legend */}
      <div className="flex flex-wrap gap-3 mt-1">
        {series.map((s, i) => (
          <span key={s.title} className="flex items-center gap-1">
            <span
              className="inline-block h-0.5 w-4 rounded"
              style={{ backgroundColor: colors[i % colors.length] }}
            />
            {s.title}
          </span>
        ))}
      </div>
    </div>
  );
};

/* eslint-disable react/prop-types, react/destructuring-assignment */
export const VoiceToneFluctuationChart = ({ item, callTranscriptPerCallId }) => {
  const maxChannels = 6;
  const { callId } = item;
  const transcriptsForThisCallId = callTranscriptPerCallId[callId] || {};
  const transcriptChannels = Object.keys(transcriptsForThisCallId)
    .slice(0, maxChannels)
    .filter((c) => c !== 'AGENT_ASSISTANT')
    .filter((c) => c !== 'AGENT')
    .filter((c) => c !== 'CALLER')
    .filter((c) => c !== 'CATEGORY_MATCH');

  const sentimentPerChannel = transcriptChannels
    .map((channel) => transcriptsForThisCallId[channel])
    .map((transcript) =>
      transcript.segments
        .filter((t) => t.sentimentWeighted)
        .reduce(
          (p, c) => [...p, { x: new Date(c.endTime * 1000), y: c.sentimentWeighted }],
          [{ x: new Date(0), y: 0 }],
        )
        .sort((a, b) => a.x - b.x),
    );

  logger.debug('sentimentPerChannel', sentimentPerChannel);

  return (
    <SimpleLineChart
      height="170"
      series={[
        {
          title: transcriptChannels[0] ? transcriptChannels[0].replace('_VOICETONE', '') : 'n/a',
          data: sentimentPerChannel[0] || [],
        },
        {
          title: transcriptChannels[1] ? transcriptChannels[1].replace('_VOICETONE', '') : 'n/a',
          data: sentimentPerChannel[1] || [],
        },
      ]}
      yDomain={[-1, 1]}
      xTitle="Time"
      yTitle="Fluctuation (30sec rolling window)"
    />
  );
};

export const SentimentFluctuationChart = ({ item, callTranscriptPerCallId }) => {
  const maxChannels = 6;
  const { callId } = item;
  const transcriptsForThisCallId = callTranscriptPerCallId[callId] || {};
  const transcriptChannels = Object.keys(transcriptsForThisCallId)
    .slice(0, maxChannels)
    .filter((c) => c !== 'AGENT_ASSISTANT')
    .filter((c) => c !== 'AGENT_VOICETONE')
    .filter((c) => c !== 'CALLER_VOICETONE')
    .filter((c) => c !== 'CATEGORY_MATCH');

  const sentimentPerChannel = transcriptChannels
    .map((channel) => transcriptsForThisCallId[channel])
    .map((transcript) =>
      transcript.segments
        .filter((t) => t.sentimentWeighted)
        .reduce(
          (p, c) => [...p, { x: new Date(c.endTime * 1000), y: c.sentimentWeighted }],
          [{ x: new Date(0), y: 0 }],
        )
        .sort((a, b) => a.x - b.x),
    );

  logger.debug('sentimentPerChannel', sentimentPerChannel);

  return (
    <SimpleLineChart
      height="80"
      series={[
        { title: transcriptChannels[0] || 'n/a', data: sentimentPerChannel[0] || [] },
        { title: transcriptChannels[1] || 'n/a', data: sentimentPerChannel[1] || [] },
      ]}
      yDomain={[-5, 5]}
      xTitle="Time"
      yTitle="Sentiment Fluctuation"
    />
  );
};

export const SentimentPerQuarterChart = ({ item, callTranscriptPerCallId }) => {
  const maxChannels = 6;
  const { callId } = item;
  const transcriptsForThisCallId = callTranscriptPerCallId[callId] || {};
  const transcriptChannels = Object.keys(transcriptsForThisCallId)
    .slice(0, maxChannels)
    .filter((c) => c !== 'AGENT_ASSISTANT')
    .filter((c) => c !== 'AGENT_VOICETONE')
    .filter((c) => c !== 'CALLER_VOICETONE')
    .filter((c) => c !== 'CATEGORY_MATCH');

  const sentimentByQuarterPerChannel = transcriptChannels
    .map((channel) => item?.sentiment?.SentimentByPeriod?.QUARTER[channel] || [])
    .map((sentimentByQuarter) =>
      sentimentByQuarter
        .filter((s) => s.EndOffsetMillis > 0)
        .reduce(
          (p, c) => [...p, { x: new Date(c.EndOffsetMillis), y: c.Score }],
          [{ x: new Date(0), y: 0 }],
        ),
    );

  logger.debug('sentimentByQuarterPerChannel', sentimentByQuarterPerChannel);

  return (
    <SimpleLineChart
      height="80"
      series={[
        { title: transcriptChannels[0] || 'n/a', data: sentimentByQuarterPerChannel[0] || [] },
        { title: transcriptChannels[1] || 'n/a', data: sentimentByQuarterPerChannel[1] || [] },
      ]}
      yDomain={[-5, 5]}
      xTitle="Time"
      yTitle="Average Sentiment Per Quarter"
    />
  );
};
