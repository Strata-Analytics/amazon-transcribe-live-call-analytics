// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { cn } from '../../lib/utils';

const AGENT_CHAT_URL = process.env.REACT_APP_AGENT_CHAT_URL;

const QUICK_ACTIONS = [
  { id: 'SUMMARIZE_CURRENT_CALL', label: 'Summarize call' },
  { id: 'IDENTIFY_CURRENT_TOPIC', label: 'Current topic' },
  { id: 'SUGGEST_RETENTION_SCRIPT', label: 'Retention script' },
  { id: 'SUGGEST_UPSELL_SCRIPT', label: 'Upsell script' },
  { id: 'SUGGEST_CLOSING_SCRIPT', label: 'Closing script' },
];

const AgentChatPanel = ({ callId }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const addAssistantMessage = (content, error = false) => {
    setMessages((prev) => [...prev, { role: 'assistant', content, error }]);
  };

  const sendRequest = async (payload) => {
    if (loading) return;
    setLoading(true);
    try {
      const res = await fetch(AGENT_CHAT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ call_id: callId, ...payload }),
      });
      if (!res.ok) throw new Error(`Error ${res.status}: ${res.statusText}`);
      const data = await res.json();
      const text = typeof data === 'string'
        ? data
        : (data.message || data.response || data.text || data.content || JSON.stringify(data));
      addAssistantMessage(text);
    } catch (err) {
      addAssistantMessage(`Error contacting agent: ${err.message}`, true);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = () => {
    const text = input.trim();
    if (!text || loading) return;
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');
    sendRequest({ message: text });
  };

  const handleQuickAction = (actionId) => {
    if (loading) return;
    const label = QUICK_ACTIONS.find((a) => a.id === actionId)?.label || actionId;
    setMessages((prev) => [...prev, { role: 'user', content: label }]);
    sendRequest({ button_action: actionId });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border border-border rounded-lg bg-background flex flex-col overflow-hidden sticky top-4 h-[calc(100vh-120px)]">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
        <Bot className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold text-foreground">AI Agent</span>
      </div>

      <div className="px-3 pt-2.5 pb-2 flex flex-wrap gap-1.5 border-b border-border flex-none">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.id}
            type="button"
            onClick={() => handleQuickAction(action.id)}
            disabled={loading}
            className="px-2.5 py-1 text-xs rounded-full border border-border bg-background hover:bg-accent hover:text-foreground text-muted-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {action.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-2 text-muted-foreground">
            <Bot className="h-8 w-8 opacity-25" />
            <p className="text-sm">Use the buttons or ask a question about the call.</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div
              className={cn(
                'max-w-[88%] rounded-lg px-3 py-2 text-sm',
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : msg.error
                    ? 'bg-destructive/10 text-destructive border border-destructive/20'
                    : 'bg-muted text-foreground',
              )}
            >
              {msg.role === 'assistant' ? (
                <ReactMarkdown
                  rehypePlugins={[rehypeRaw]}
                  className="prose prose-sm max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                >
                  {msg.content}
                </ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-lg px-3 py-2 text-sm text-muted-foreground">
              <span className="animate-pulse">Thinking…</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="px-3 py-2.5 border-t border-border flex gap-2 flex-none">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about the call…"
          disabled={loading}
          className="h-9 text-sm"
        />
        <Button
          size="sm"
          onClick={handleSend}
          disabled={!input.trim() || loading}
          className="h-9 px-3 flex-none"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
};

export default AgentChatPanel;
