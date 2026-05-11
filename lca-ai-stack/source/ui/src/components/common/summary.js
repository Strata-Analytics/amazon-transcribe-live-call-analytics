// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export const getTextOnlySummary = (callSummaryText) => {
  if (!callSummaryText) {
    return 'Not available';
  }
  let summary = callSummaryText;
  try {
    const jsonObj = JSON.parse(summary);
    // Do a case-insensitive search for 'summary' in the JSON object keys
    const summaryKey = Object.keys(jsonObj).find((key) => key.toLowerCase() === 'summary');
    if (summaryKey !== undefined) {
      summary = jsonObj[summaryKey];
    } else if (Object.keys(jsonObj).length > 0) {
      // If 'summary' is not found, use the first key as the summary
      summary = Object.keys(jsonObj)[0] || '';
      summary = jsonObj[summary];
    }
  } catch (e) {
    return callSummaryText;
  }
  return summary;
};

const markdownToHtml = (text) =>
  String(text)
    .replace(/```[\w]*\n?/g, '')
    .replace(/\\\*/g, '*')
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const html = line.replace(/\*\*(.*?)\*\*/g, '<span style="font-weight:600">$1</span>');
      return `<p>${html}</p>`;
    })
    .join('');

export const getHtmlSummary = (callSummaryText) => {
  if (!callSummaryText) return '<p>Not available</p>';
  try {
    const jsonSummary = JSON.parse(callSummaryText);
    return Object.entries(jsonSummary)
      .map(([key, value], i) => `${i > 0 ? '<hr style="border:none; border-top:1px solid var(--border); margin:0.75rem 0"/>' : ''}<p><strong>${key}</strong></p>${markdownToHtml(String(value))}`)
      .join('');
  } catch (e) {
    return markdownToHtml(callSummaryText);
  }
};

export const getMarkdownSummary = getHtmlSummary;

export default getTextOnlySummary;
