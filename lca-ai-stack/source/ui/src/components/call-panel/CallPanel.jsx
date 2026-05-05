// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useRef, useState } from 'react';

import rehypeRaw from 'rehype-raw';
import ReactMarkdown from 'react-markdown';
import { TranslateClient, TranslateTextCommand } from '@aws-sdk/client-translate';
import { Logger } from 'aws-amplify';
import { StandardRetryStrategy } from '@aws-sdk/middleware-retry';
import { ChevronDown, ChevronUp, Download, ExternalLink } from 'lucide-react';

import { getMarkdownSummary } from '../common/summary';
import RecordingPlayer from '../recording-player';
import useSettingsContext from '../../contexts/settings';
import { DONE_STATUS, IN_PROGRESS_STATUS } from '../common/get-recording-status';
import { InfoLink } from '../common/info-link';
import { getWeightedSentimentLabel } from '../common/sentiment';
import {
  VoiceToneFluctuationChart,
  SentimentFluctuationChart,
  SentimentPerQuarterChart,
} from './sentiment-charts';
import './CallPanel.css';
import { SentimentTrendIcon } from '../sentiment-trend-icon/SentimentTrendIcon';
import { SentimentIcon } from '../sentiment-icon/SentimentIcon';
import { exportToExcel } from '../common/download-func';
import useAppContext from '../../contexts/app';
import awsExports from '../../aws-exports';
import { Button } from '../ui/button';
import { cn } from '../../lib/utils';

const logger = new Logger('CallPanel');

const piiTypes = [
  'BANK_ACCOUNT_NUMBER', 'BANK_ROUTING', 'CREDIT_DEBIT_NUMBER', 'CREDIT_DEBIT_CVV',
  'CREDIT_DEBIT_EXPIRY', 'PIN', 'EMAIL', 'ADDRESS', 'NAME', 'PHONE', 'SSN',
];
const piiTypesSplitRegEx = new RegExp(`\\[(${piiTypes.join('|')})\\]`);

const MAXIMUM_ATTEMPTS = 100;
const MAXIMUM_RETRY_DELAY = 1000;
const PAUSE_TO_MERGE_IN_SECONDS = 1;

const languageCodes = [
  { value: '', label: 'Choose a Language' },
  { value: 'af', label: 'Afrikaans' },
  { value: 'sq', label: 'Albanian' },
  { value: 'am', label: 'Amharic' },
  { value: 'ar', label: 'Arabic' },
  { value: 'hy', label: 'Armenian' },
  { value: 'az', label: 'Azerbaijani' },
  { value: 'bn', label: 'Bengali' },
  { value: 'bs', label: 'Bosnian' },
  { value: 'bg', label: 'Bulgarian' },
  { value: 'ca', label: 'Catalan' },
  { value: 'zh', label: 'Chinese (Simplified)' },
  { value: 'zh-TW', label: 'Chinese (Traditional)' },
  { value: 'hr', label: 'Croatian' },
  { value: 'cs', label: 'Czech' },
  { value: 'da', label: 'Danish' },
  { value: 'fa-AF', label: 'Dari' },
  { value: 'nl', label: 'Dutch' },
  { value: 'en', label: 'English' },
  { value: 'et', label: 'Estonian' },
  { value: 'fa', label: 'Farsi (Persian)' },
  { value: 'tl', label: 'Filipino, Tagalog' },
  { value: 'fi', label: 'Finnish' },
  { value: 'fr', label: 'French' },
  { value: 'fr-CA', label: 'French (Canada)' },
  { value: 'ka', label: 'Georgian' },
  { value: 'de', label: 'German' },
  { value: 'el', label: 'Greek' },
  { value: 'gu', label: 'Gujarati' },
  { value: 'ht', label: 'Haitian Creole' },
  { value: 'ha', label: 'Hausa' },
  { value: 'he', label: 'Hebrew' },
  { value: 'hi', label: 'Hindi' },
  { value: 'hu', label: 'Hungarian' },
  { value: 'is', label: 'Icelandic' },
  { value: 'id', label: 'Indonesian' },
  { value: 'ga', label: 'Irish' },
  { value: 'it', label: 'Italian' },
  { value: 'ja', label: 'Japanese' },
  { value: 'kn', label: 'Kannada' },
  { value: 'kk', label: 'Kazakh' },
  { value: 'ko', label: 'Korean' },
  { value: 'lv', label: 'Latvian' },
  { value: 'lt', label: 'Lithuanian' },
  { value: 'mk', label: 'Macedonian' },
  { value: 'ms', label: 'Malay' },
  { value: 'ml', label: 'Malayalam' },
  { value: 'mt', label: 'Maltese' },
  { value: 'mr', label: 'Marathi' },
  { value: 'mn', label: 'Mongolian' },
  { value: 'no', label: 'Norwegian (Bokmål)' },
  { value: 'ps', label: 'Pashto' },
  { value: 'pl', label: 'Polish' },
  { value: 'pt', label: 'Portuguese (Brazil)' },
  { value: 'pt-PT', label: 'Portuguese (Portugal)' },
  { value: 'pa', label: 'Punjabi' },
  { value: 'ro', label: 'Romanian' },
  { value: 'ru', label: 'Russian' },
  { value: 'sr', label: 'Serbian' },
  { value: 'si', label: 'Sinhala' },
  { value: 'sk', label: 'Slovak' },
  { value: 'sl', label: 'Slovenian' },
  { value: 'so', label: 'Somali' },
  { value: 'es', label: 'Spanish' },
  { value: 'es-MX', label: 'Spanish (Mexico)' },
  { value: 'sw', label: 'Swahili' },
  { value: 'sv', label: 'Swedish' },
  { value: 'ta', label: 'Tamil' },
  { value: 'te', label: 'Telugu' },
  { value: 'th', label: 'Thai' },
  { value: 'tr', label: 'Turkish' },
  { value: 'uk', label: 'Ukrainian' },
  { value: 'ur', label: 'Urdu' },
  { value: 'uz', label: 'Uzbek' },
  { value: 'vi', label: 'Vietnamese' },
  { value: 'cy', label: 'Welsh' },
];

/* ── Layout primitives ─────────────────────────────────────────────────── */

/* eslint-disable react/prop-types */
const Card = ({ header, actions, children, className }) => (
  <div className={cn('border border-border rounded-lg bg-background overflow-hidden', className)}>
    {(header || actions) && (
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">{header}</div>
        {actions && <div className="flex items-center gap-1.5">{actions}</div>}
      </div>
    )}
    <div className="p-4">{children}</div>
  </div>
);

const FieldLabel = ({ children }) => (
  <div className="mb-0.5 text-xs font-medium text-muted-foreground">{children}</div>
);

const statusStyles = {
  success: 'text-green-600', error: 'text-destructive', warning: 'text-yellow-600',
  'in-progress': 'text-blue-600', info: 'text-blue-600', stopped: 'text-muted-foreground',
  loading: 'text-muted-foreground',
};
const statusDots = {
  success: '●', error: '●', warning: '▲', 'in-progress': '◐',
  info: 'ℹ', stopped: '■', loading: '○',
};
const StatusIndicator = ({ type, children }) => (
  <span className={cn('inline-flex items-center gap-1.5 text-sm', statusStyles[type] || 'text-muted-foreground')}>
    <span aria-hidden="true">{statusDots[type] || '●'}</span>
    {children}
  </span>
);

const Toggle = ({ checked, onChange, disabled, label }) => (
  <label className={cn('flex items-center gap-1.5 cursor-pointer text-sm', disabled && 'opacity-50 cursor-not-allowed')}>
    <input
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
      className="h-4 w-4 rounded border-input accent-primary"
    />
    {label && <span>{label}</span>}
  </label>
);

const SimpleTabs = ({ tabs }) => {
  const [active, setActive] = useState(tabs[0]?.id);
  const current = tabs.find((t) => t.id === active);
  return (
    <div>
      <div className="flex border-b border-border mb-3 gap-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActive(t.id)}
            className={cn(
              'px-3 pb-2 text-sm transition-colors',
              active === t.id
                ? 'border-b-2 border-primary text-primary font-medium'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div>{current?.content}</div>
    </div>
  );
};

/* ── Sub-components ────────────────────────────────────────────────────── */

const CallAttributes = ({ item, setToolsOpen }) => (
  <Card
    header={<>Call Attributes <InfoLink onFollow={() => setToolsOpen(true)} /></>}
    actions={
      <Button
        variant="ghost"
        size="icon"
        onClick={() => exportToExcel([item], 'call-details')}
        aria-label="Download"
      >
        <Download className="h-4 w-4" />
      </Button>
    }
  >
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-4 divide-x-0">
      {[
        { label: 'Call ID', value: item.callId },
        { label: 'Agent', value: item.agentId },
        { label: 'Initiation Timestamp', value: item.initiationTimeStamp },
        { label: 'Last Update Timestamp', value: item.updatedAt },
        { label: 'Duration', value: item.conversationDurationTimeStamp },
        { label: 'Caller Phone Number', value: item.callerPhoneNumber },
        { label: 'System Phone Number', value: item.systemPhoneNumber },
        {
          label: 'Status',
          value: (
            <StatusIndicator type={item.recordingStatusIcon}>
              {item.recordingStatusLabel}
            </StatusIndicator>
          ),
        },
      ].map(({ label, value }) => (
        <div key={label}>
          <FieldLabel>{label}</FieldLabel>
          <div className="text-sm text-foreground">{value}</div>
        </div>
      ))}
      {item?.pcaUrl?.length > 0 && (
        <div>
          <FieldLabel>Post Call Analytics</FieldLabel>
          <a
            href={item.pcaUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            Open in Post Call Analytics
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      )}
      {item?.recordingUrl?.length > 0 && item?.recordingStatusLabel !== IN_PROGRESS_STATUS && (
        <div>
          <FieldLabel>Recording Audio</FieldLabel>
          <RecordingPlayer recordingUrl={item.recordingUrl} />
        </div>
      )}
    </div>
  </Card>
);

const CallCategories = ({ item }) => {
  const { settings } = useSettingsContext();
  const regex = settings?.CategoryAlertRegex ?? '.*';
  const categories = item.callCategories || [];

  const categoryComponents = categories.map((t, i) => {
    const isAlert = t.match(regex);
    return (
      // eslint-disable-next-line react/no-array-index-key
      <div key={`call-category-${i}`} className={isAlert ? 'transcript-segment-category-match-alert' : 'transcript-segment-category-match'}>
        <ReactMarkdown rehypePlugins={[rehypeRaw]}>{t.trim()}</ReactMarkdown>
      </div>
    );
  });

  return (
    <Card
      header={
        <>
          Call Categories
          <a
            className="ml-1 text-xs text-primary hover:underline"
            target="_blank"
            rel="noreferrer"
            href="https://docs.aws.amazon.com/transcribe/latest/dg/call-analytics-create-categories.html"
          >
            Info
          </a>
        </>
      }
    >
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {categoryComponents}
      </div>
    </Card>
  );
};

const CallSummary = ({ item }) => (
  <Card
    header={
      <>
        Call Summary
        <a
          className="ml-1 text-xs text-primary hover:underline"
          target="_blank"
          rel="noreferrer"
          href="https://docs.aws.amazon.com/transcribe/latest/dg/call-analytics-insights.html#call-analytics-insights-summarization"
        >
          Info
        </a>
      </>
    }
  >
    <div className="grid gap-4 grid-cols-1 sm:grid-cols-2">
      <SimpleTabs
        tabs={[
          {
            label: 'Transcript Summary',
            id: 'summary',
            content: (
              <div className="markdown-prose text-sm text-foreground">
                <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                  {getMarkdownSummary(item.callSummaryText) ?? 'No summary available'}
                </ReactMarkdown>
              </div>
            ),
          },
        ]}
      />
      <SimpleTabs
        tabs={[
          {
            label: 'Issues',
            id: 'issues',
            content: (
              <div className="markdown-prose issue-detected text-sm text-foreground">
                <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                  {item.issuesDetected ?? 'No issue detected'}
                </ReactMarkdown>
              </div>
            ),
          },
        ]}
      />
    </div>
  </Card>
);

const getSentimentImage = (segment) => {
  const { sentiment, sentimentScore, sentimentWeighted } = segment;
  if (!sentiment) {
    return <div className="sentiment-image" />;
  }
  const weightedSentimentLabel = getWeightedSentimentLabel(sentimentWeighted);
  const tooltipText = [
    `Sentiment: ${sentiment}`,
    `Scores: ${JSON.stringify(sentimentScore)}`,
    `Weighted: ${sentimentWeighted}`,
  ].join('\n');
  return (
    <div
      className="sentiment-image-popover cursor-help"
      title={tooltipText}
    >
      <SentimentIcon sentiment={weightedSentimentLabel} />
    </div>
  );
};

const getTimestampFromSeconds = (secs) => {
  if (!secs || Number.isNaN(secs)) return '00:00.0';
  return new Date(secs * 1000).toISOString().substr(14, 7);
};

const TranscriptContent = ({ segment, translateCache }) => {
  const { settings } = useSettingsContext();
  const regex = settings?.CategoryAlertRegex ?? '.*';

  const { transcript, segmentId, channel, targetLanguage, agentTranscript, translateOn } = segment;
  const k = segmentId.concat('-', targetLanguage);

  const currTranslated =
    translateOn && targetLanguage !== '' && translateCache[k]?.translated !== undefined
      ? translateCache[k].translated
      : '';

  const result = currTranslated ?? '';
  const transcriptPiiSplit = transcript.split(piiTypesSplitRegEx);

  const transcriptComponents = transcriptPiiSplit.map((t, i) => {
    if (piiTypes.includes(t)) {
      return (
        // eslint-disable-next-line react/no-array-index-key
        <span
          key={`${segmentId}-pii-${i}`}
          className="inline-flex items-center rounded-full bg-red-100 text-red-700 px-2 py-0.5 text-xs font-medium"
        >
          {t}
        </span>
      );
    }

    let className = '';
    let text = t;
    let translatedText = result;
    switch (channel) {
      case 'AGENT_ASSISTANT':
        className = 'transcript-segment-agent-assist';
        break;
      case 'AGENT':
        text = agentTranscript !== undefined && agentTranscript ? text : '';
        translatedText = agentTranscript !== undefined && agentTranscript ? translatedText : '';
        break;
      case 'CATEGORY_MATCH':
        if (text.match(regex)) {
          className = 'transcript-segment-category-match-alert';
          text = `Alert: ${text}`;
        } else {
          className = 'transcript-segment-category-match';
          text = `Category: ${text}`;
        }
        break;
      default:
        break;
    }

    return (
      // eslint-disable-next-line react/no-array-index-key
      <div key={`${segmentId}-text-${i}`} className={className}>
        <ReactMarkdown rehypePlugins={[rehypeRaw]}>{text.trim()}</ReactMarkdown>
        <ReactMarkdown className="translated-text" rehypePlugins={[rehypeRaw]}>{translatedText.trim()}</ReactMarkdown>
      </div>
    );
  });

  return <div className="flex flex-wrap items-start gap-1">{transcriptComponents}</div>;
};

const TranscriptSegment = ({ segment, translateCache }) => {
  const { channel } = segment;

  if (channel === 'CATEGORY_MATCH') {
    const categoryText = `${segment.transcript}`;
    const newSegment = { ...segment, transcript: categoryText };
    return (
      <div className="transcript-segment grid gap-2" style={{ gridTemplateColumns: '32px 1fr' }}>
        {getSentimentImage(newSegment)}
        <div>
          <TranscriptContent segment={newSegment} translateCache={translateCache} />
        </div>
      </div>
    );
  }

  const channelClass = channel === 'AGENT_ASSISTANT' ? 'transcript-segment-agent-assist' : '';
  return (
    <div className="transcript-segment grid gap-2" style={{ gridTemplateColumns: '32px 1fr' }}>
      {getSentimentImage(segment)}
      <div className={cn('space-y-0.5', channelClass)}>
        <div className="flex items-center gap-2">
          <strong className="text-xs font-semibold">{segment.channel}</strong>
          <span className="text-xs text-muted-foreground">
            {`${getTimestampFromSeconds(segment.startTime)} - ${getTimestampFromSeconds(segment.endTime)}`}
          </span>
        </div>
        <TranscriptContent segment={segment} translateCache={translateCache} />
      </div>
    </div>
  );
};

const formatTranscriptExcel = (item, callTranscriptPerCallId) => {
  const maxChannels = 4;
  const { callId } = item;
  const transcriptsForThisCallId = callTranscriptPerCallId[callId] || {};
  const transcriptChannels = Object.keys(transcriptsForThisCallId).slice(0, maxChannels);
  return transcriptChannels
    .map((c) => transcriptsForThisCallId[c].segments)
    .reduce((p, c) => [...p, ...c].sort((a, b) => a.endTime - b.endTime), [])
    .map((s) => s?.segmentId && s?.createdAt && s);
};

const shouldAppendToPreviousSegment = ({ previous, current }) =>
  previous.speaker === current.speaker
  && previous.channel === current.channel
  && current.startTime - previous.endTime < PAUSE_TO_MERGE_IN_SECONDS;

const appendToPreviousSegment = ({ previous, current }) => {
  /* eslint-disable no-param-reassign */
  previous.transcript += ` ${current.transcript}`;
  previous.endTime = current.endTime;
  previous.isPartial = current.isPartial;
};

const CallInProgressTranscript = ({
  item,
  callTranscriptPerCallId,
  autoScroll,
  translateClient,
  targetLanguage,
  agentTranscript,
  translateOn,
  collapseSentiment,
}) => {
  const bottomRef = useRef();
  const [turnByTurnSegments, setTurnByTurnSegments] = useState([]);
  const [translateCache, setTranslateCache] = useState({});
  const [cacheSeen, setCacheSeen] = useState({});
  const [lastUpdated, setLastUpdated] = useState(Date.now());
  const [updateFlag, setUpdateFlag] = useState(false);

  const maxChannels = 6;
  const { callId } = item;
  const transcriptsForThisCallId = callTranscriptPerCallId[callId] || {};
  const transcriptChannels = Object.keys(transcriptsForThisCallId).slice(0, maxChannels);

  const getSegments = () =>
    transcriptChannels
      .map((c) => transcriptsForThisCallId[c].segments)
      .reduce((p, c) => [...p, ...c].sort((a, b) => a.endTime - b.endTime), [])
      .reduce((accumulator, current) => {
        if (
          !accumulator.length
          || !shouldAppendToPreviousSegment({ previous: accumulator[accumulator.length - 1], current })
          || translateOn
        ) {
          accumulator.push({ ...current });
        } else {
          appendToPreviousSegment({ previous: accumulator[accumulator.length - 1], current });
        }
        return accumulator;
      }, []);

  const updateTranslateCache = (seg) => {
    const promises = [];
    for (let i = 0; i < seg.length; i += 1) {
      const k = seg[i].segmentId.concat('-', targetLanguage);
      if (translateCache[k] === undefined) {
        const params = {
          Text: seg[i].transcript,
          SourceLanguageCode: 'auto',
          TargetLanguageCode: targetLanguage,
        };
        const command = new TranslateTextCommand(params);
        logger.debug('Translate API being invoked for:', seg[i].transcript, targetLanguage);
        promises.push(
          translateClient.send(command).then(
            (data) => {
              const n = {};
              logger.debug('Translate API response:', seg[i].transcript, targetLanguage, data.TranslatedText);
              n[k] = { cacheId: k, transcript: seg[i].transcript, translated: data.TranslatedText };
              return n;
            },
            (error) => { logger.debug('Error from translate:', error); },
          ),
        );
      }
    }
    return promises;
  };

  useEffect(() => {
    if (translateOn && targetLanguage !== '' && item.recordingStatusLabel !== IN_PROGRESS_STATUS) {
      const promises = updateTranslateCache(getSegments());
      Promise.all(promises).then((results) => {
        if (results.length > 0) {
          setTranslateCache((state) => ({ ...state, ...results.reduce((a, b) => ({ ...a, ...b })) }));
          setUpdateFlag((state) => !state);
        }
      });
    }
  }, [targetLanguage, agentTranscript, translateOn, item.recordingStatusLabel]);

  useEffect(() => {
    (async () => {
      const c = getSegments();
      if (
        translateOn && targetLanguage !== '' && c.length > 0
        && item.recordingStatusLabel === IN_PROGRESS_STATUS
      ) {
        const k = c[c.length - 1].segmentId.concat('-', targetLanguage);
        const n = {};
        if (c[c.length - 1].isPartial === false && cacheSeen[k] === undefined) {
          n[k] = { seen: true };
          setCacheSeen((state) => ({ ...state, ...n }));
          if (translateCache[k] === undefined) {
            const params = {
              Text: c[c.length - 1].transcript,
              SourceLanguageCode: 'auto',
              TargetLanguageCode: targetLanguage,
            };
            const command = new TranslateTextCommand(params);
            logger.debug('Translate API being invoked for:', c[c.length - 1].transcript, targetLanguage);
            try {
              const data = await translateClient.send(command);
              const o = {};
              logger.debug('Translate API response:', c[c.length - 1].transcript, data.TranslatedText);
              o[k] = { cacheId: k, transcript: c[c.length - 1].transcript, translated: data.TranslatedText };
              setTranslateCache((state) => ({ ...state, ...o }));
            } catch (error) {
              logger.debug('Error from translate:', error);
            }
          }
        }
        if (Date.now() - lastUpdated > 500) {
          setUpdateFlag((state) => !state);
          logger.debug('Updating turn by turn with latest cache');
        }
      }
      setLastUpdated(Date.now());
    })();
  }, [callTranscriptPerCallId]);

  const getTurnByTurnSegments = () => {
    const segs = transcriptChannels
      .map((c) => transcriptsForThisCallId[c].segments)
      .reduce((p, c) => [...p, ...c].sort((a, b) => a.endTime - b.endTime), [])
      .map((c) => {
        const t = c;
        t.agentTranscript = agentTranscript;
        t.targetLanguage = targetLanguage;
        t.translateOn = translateOn;
        return t;
      })
      .map(
        (s) =>
          s?.segmentId && s?.createdAt
          && (s.agentTranscript === undefined || s.agentTranscript || s.channel !== 'AGENT')
          && s.channel !== 'AGENT_VOICETONE'
          && s.channel !== 'CALLER_VOICETONE'
          && (
            <TranscriptSegment
              key={`${s.segmentId}-${s.createdAt}`}
              segment={s}
              translateCache={translateCache}
            />
          ),
      );

    segs.push(<div key="bottom" ref={bottomRef} />);
    return segs;
  };

  useEffect(() => {
    setTurnByTurnSegments(getTurnByTurnSegments);
  }, [callTranscriptPerCallId, item.recordingStatusLabel, targetLanguage, agentTranscript, translateOn, updateFlag]);

  useEffect(() => {
    if (
      item.recordingStatusLabel === IN_PROGRESS_STATUS
      && autoScroll
      && bottomRef.current?.scrollIntoView
    ) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [turnByTurnSegments, autoScroll, item.recordingStatusLabel, targetLanguage, agentTranscript, translateOn]);

  return (
    <div
      style={{
        overflowY: 'auto',
        maxHeight: collapseSentiment ? '34vh' : '68vh',
        paddingLeft: 12,
        paddingTop: 8,
        paddingRight: 12,
      }}
    >
      <div className="divide-y divide-border [&>*]:py-3">
        {turnByTurnSegments}
      </div>
    </div>
  );
};

const getAgentAssistPanel = (item, collapseSentiment) => {
  if (process.env.REACT_APP_ENABLE_LEX_AGENT_ASSIST === 'true') {
    return (
      <Card header="Agent Assist Bot">
        <div style={{ height: collapseSentiment ? '34vh' : '68vh' }}>
          <iframe
            style={{ border: '0px', height: collapseSentiment ? '34vh' : '68vh', margin: 0 }}
            title="Agent Assist"
            src={`/index-lexwebui.html?callId=${item.callId}`}
            width="100%"
          />
        </div>
      </Card>
    );
  }
  return null;
};

const getTranscriptContent = ({
  item, callTranscriptPerCallId, autoScroll, translateClient,
  targetLanguage, agentTranscript, translateOn, collapseSentiment,
}) => {
  switch (item.recordingStatusLabel) {
    case DONE_STATUS:
    case IN_PROGRESS_STATUS:
    default:
      return (
        <CallInProgressTranscript
          item={item}
          callTranscriptPerCallId={callTranscriptPerCallId}
          autoScroll={autoScroll}
          translateClient={translateClient}
          targetLanguage={targetLanguage}
          agentTranscript={agentTranscript}
          translateOn={translateOn}
          collapseSentiment={collapseSentiment}
        />
      );
  }
};

const CallTranscriptContainer = ({
  setToolsOpen,
  item,
  callTranscriptPerCallId,
  translateClient,
  collapseSentiment,
}) => {
  const [autoScroll, setAutoScroll] = useState(item.recordingStatusLabel === IN_PROGRESS_STATUS);
  const [autoScrollDisabled, setAutoScrollDisabled] = useState(item.recordingStatusLabel !== IN_PROGRESS_STATUS);
  const [translateOn, setTranslateOn] = useState(false);
  const [targetLanguage, setTargetLanguage] = useState(localStorage.getItem('targetLanguage') || '');
  const [agentTranscript, setAgentTranscript] = useState(true);

  const handleLanguageSelect = (e) => {
    setTargetLanguage(e.target.value);
    localStorage.setItem('targetLanguage', e.target.value);
  };

  useEffect(() => {
    setAutoScrollDisabled(item.recordingStatusLabel !== IN_PROGRESS_STATUS);
    setAutoScroll(item.recordingStatusLabel === IN_PROGRESS_STATUS);
  }, [item.recordingStatusLabel]);

  const transcriptCols = process.env.REACT_APP_ENABLE_LEX_AGENT_ASSIST === 'true' ? 'grid-cols-1 sm:grid-cols-[2fr_1fr]' : 'grid-cols-1';

  return (
    <div className={cn('grid gap-4', transcriptCols)}>
      <Card
        header={
          <>
            Call Transcript
            <InfoLink onFollow={() => setToolsOpen(true)} />
          </>
        }
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <Toggle
              checked={autoScroll}
              onChange={setAutoScroll}
              disabled={autoScrollDisabled}
              label="Auto Scroll"
            />
            <Toggle
              checked={agentTranscript}
              onChange={setAgentTranscript}
              label="Show Agent Transcripts?"
            />
            <Toggle
              checked={translateOn}
              onChange={setTranslateOn}
              label="Enable Translation"
            />
            {translateOn && (
              <select
                value={targetLanguage}
                onChange={handleLanguageSelect}
                className="h-8 rounded border border-input bg-background px-2 text-sm"
              >
                {languageCodes.map(({ value, label }) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => exportToExcel(formatTranscriptExcel(item, callTranscriptPerCallId), 'call-transcript')}
              aria-label="Download transcript"
            >
              <Download className="h-4 w-4" />
            </Button>
          </div>
        }
      >
        {getTranscriptContent({
          item,
          callTranscriptPerCallId,
          autoScroll,
          translateClient,
          targetLanguage,
          agentTranscript,
          translateOn,
          collapseSentiment,
        })}
      </Card>
      {getAgentAssistPanel(item, collapseSentiment)}
    </div>
  );
};

const VoiceToneContainer = ({ item, callTranscriptPerCallId, collapseVoiceTone, setCollapseVoiceTone }) => (
  <Card
    header={
      <>
        Voice Tone Analysis
        <a
          className="ml-1 text-xs text-primary hover:underline"
          target="_blank"
          rel="noreferrer"
          href="https://docs.aws.amazon.com/chime-sdk/latest/dg/call-analytics.html"
        >
          Info
        </a>
      </>
    }
    actions={
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setCollapseVoiceTone(!collapseVoiceTone)}
        aria-label={collapseVoiceTone ? 'Collapse' : 'Expand'}
      >
        {collapseVoiceTone ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </Button>
    }
  >
    {collapseVoiceTone && (
      <VoiceToneFluctuationChart item={item} callTranscriptPerCallId={callTranscriptPerCallId} />
    )}
  </Card>
);

const CallStatsContainer = ({ item, callTranscriptPerCallId, collapseSentiment, setCollapseSentiment }) => (
  <Card
    header={
      <>
        Call Sentiment Analysis
        <a
          className="ml-1 text-xs text-primary hover:underline"
          target="_blank"
          rel="noreferrer"
          href="https://docs.aws.amazon.com/transcribe/latest/dg/call-analytics-insights.html#call-analytics-insights-sentiment"
        >
          Info
        </a>
      </>
    }
    actions={
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setCollapseSentiment(!collapseSentiment)}
        aria-label={collapseSentiment ? 'Collapse' : 'Expand'}
      >
        {collapseSentiment ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </Button>
    }
  >
    {collapseSentiment && (
      <>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <SentimentFluctuationChart item={item} callTranscriptPerCallId={callTranscriptPerCallId} />
          <SentimentPerQuarterChart item={item} callTranscriptPerCallId={callTranscriptPerCallId} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <FieldLabel>Caller Avg Sentiment:</FieldLabel>
            <div className="text-sm">
              <SentimentIcon sentiment={item.callerSentimentLabel} />
              &nbsp;{item.callerAverageSentiment?.toFixed(3)}
              <br />
              <span className="text-xs text-muted-foreground">(min: -5, max: +5)</span>
            </div>
          </div>
          <div>
            <FieldLabel>Caller Sentiment Trend:</FieldLabel>
            <SentimentTrendIcon trend={item.callerSentimentTrendLabel} />
          </div>
          <div>
            <FieldLabel>Agent Avg Sentiment:</FieldLabel>
            <div className="text-sm">
              <SentimentIcon sentiment={item.agentSentimentLabel} />
              &nbsp;{item.agentAverageSentiment?.toFixed(3)}
              <br />
              <span className="text-xs text-muted-foreground">(min: -5, max: +5)</span>
            </div>
          </div>
          <div>
            <FieldLabel>Agent Sentiment Trend:</FieldLabel>
            <SentimentTrendIcon trend={item.agentSentimentTrendLabel} />
          </div>
        </div>
      </>
    )}
  </Card>
);

export const CallPanel = ({ item, callTranscriptPerCallId, setToolsOpen }) => {
  const { currentCredentials } = useAppContext();
  const { settings } = useSettingsContext();
  const [collapseSentiment, setCollapseSentiment] = useState(false);
  const [collapseVoiceTone, setCollapseVoiceTone] = useState(false);

  const enableVoiceTone = settings?.EnableVoiceToneAnalysis === 'true';

  const customRetryStrategy = new StandardRetryStrategy(
    async () => MAXIMUM_ATTEMPTS,
    {
      delayDecider: (_, attempts) => Math.floor(Math.min(MAXIMUM_RETRY_DELAY, 2 ** attempts * 10)),
    },
  );

  let translateClient = new TranslateClient({
    region: awsExports.aws_project_region,
    credentials: currentCredentials,
    maxAttempts: MAXIMUM_ATTEMPTS,
    retryStrategy: customRetryStrategy,
  });

  useEffect(() => {
    logger.debug('Translate client with refreshed credentials');
    translateClient = new TranslateClient({
      region: awsExports.aws_project_region,
      credentials: currentCredentials,
      maxAttempts: MAXIMUM_ATTEMPTS,
      retryStrategy: customRetryStrategy,
    });
  }, [currentCredentials]);

  return (
    <div className="space-y-4">
      <CallAttributes item={item} setToolsOpen={setToolsOpen} />
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-[2fr_1fr]">
        <CallSummary item={item} />
        <CallCategories item={item} />
      </div>
      <div className={cn('grid gap-4', enableVoiceTone ? 'grid-cols-1 sm:grid-cols-[2fr_1fr]' : 'grid-cols-1')}>
        <CallStatsContainer
          item={item}
          callTranscriptPerCallId={callTranscriptPerCallId}
          collapseSentiment={collapseSentiment}
          setCollapseSentiment={setCollapseSentiment}
        />
        {enableVoiceTone && (
          <VoiceToneContainer
            item={item}
            callTranscriptPerCallId={callTranscriptPerCallId}
            collapseVoiceTone={collapseVoiceTone}
            setCollapseVoiceTone={setCollapseVoiceTone}
          />
        )}
      </div>
      <CallTranscriptContainer
        item={item}
        setToolsOpen={setToolsOpen}
        callTranscriptPerCallId={callTranscriptPerCallId}
        translateClient={translateClient}
        collapseSentiment={collapseSentiment}
      />
    </div>
  );
};

export default CallPanel;
