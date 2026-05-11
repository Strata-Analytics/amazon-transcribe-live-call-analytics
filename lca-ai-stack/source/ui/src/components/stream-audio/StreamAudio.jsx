// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useRef, useCallback, useEffect } from 'react';

import useWebSocket from 'react-use-websocket';

import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';

import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';

let SOURCE_SAMPLING_RATE;

const StreamAudio = () => {
  const { currentSession } = useAppContext();
  const { settings } = useSettingsContext();
  const JWT_TOKEN = currentSession.getAccessToken().getJwtToken();

  const [callMetaData, setCallMetaData] = useState({
    callId: crypto.randomUUID(),
    agentId: 'AudioStream',
    fromNumber: '+9165551234',
    toNumber: '+8001112222',
  });

  const [recording, setRecording] = useState(false);
  const [streamingStarted, setStreamingStarted] = useState(false);
  const [micInputOption, setMicInputOption] = useState({ label: 'AGENT', value: 'agent' });

  const getSocketUrl = useCallback(() => {
    console.log(`DEBUG - [${new Date().toISOString()}]: Trying to resolve websocket url...`);
    return new Promise((resolve) => {
      if (settings.WSEndpoint) {
        console.log(`DEBUG - [${new Date().toISOString()}]: Resolved Websocket URL to ${settings.WSEndpoint}`);
        resolve(settings.WSEndpoint);
      }
    });
  }, [settings.WSEndpoint]);

  const { sendMessage } = useWebSocket(getSocketUrl, {
    queryParams: { authorization: `Bearer ${JWT_TOKEN}` },
    onOpen: (event) => console.log(`DEBUG - [${new Date().toISOString()}]: Websocket onOpen: ${JSON.stringify(event)}`),
    onClose: (event) => console.log(`DEBUG - [${new Date().toISOString()}]: Websocket onClose: ${JSON.stringify(event)}`),
    onError: (event) => console.log(`DEBUG - [${new Date().toISOString()}]: Websocket onError: ${JSON.stringify(event)}`),
    shouldReconnect: () => true,
  });

  const handleCallIdChange = (e) => setCallMetaData({ ...callMetaData, callId: e.target.value });
  const handleAgentIdChange = (e) => setCallMetaData({ ...callMetaData, agentId: e.target.value });
  const handlefromNumberChange = (e) => setCallMetaData({ ...callMetaData, fromNumber: e.target.value });
  const handletoNumberChange = (e) => setCallMetaData({ ...callMetaData, toNumber: e.target.value });
  const handleMicInputOptionSelection = (e) => setMicInputOption({
    value: e.target.value,
    label: e.target.options[e.target.selectedIndex].text,
  });

  const audioProcessor = useRef();
  const audioContext = useRef();
  const displayStream = useRef();
  const micStream = useRef();
  const displayAudioSource = useRef();
  const micAudioSource = useRef();
  const channelMerger = useRef();

  const convertToMono = (audioSource) => {
    const splitter = audioContext.current.createChannelSplitter(2);
    const merger = audioContext.current.createChannelMerger(1);
    audioSource.connect(splitter);
    splitter.connect(merger, 0, 0);
    splitter.connect(merger, 1, 0);
    return merger;
  };

  const stopRecording = async () => {
    console.log(`DEBUG - [${new Date().toISOString()}]: Stopping recording...`);

    if (audioProcessor.current) {
      audioProcessor.current.port.postMessage({ message: 'UPDATE_RECORDING_STATE', setRecording: false });
      audioProcessor.current.port.close();
      audioProcessor.current.disconnect();
      displayStream.current.getTracks().forEach((track) => track.stop());
      micStream.current.getTracks().forEach((track) => track.stop());
      audioContext.current.close().then(() => console.log('AudioContext closed.'));
    } else {
      console.log(`DEBUG - [${new Date().toISOString()}]: Error: AudioWorklet Processor node is not active.`);
      setRecording(false);
    }
    if (streamingStarted && !recording) {
      callMetaData.callEvent = 'END';
      console.log(`DEBUG - [${new Date().toISOString()}]: Send Call END msg: ${JSON.stringify(callMetaData)}`);
      sendMessage(JSON.stringify(callMetaData));
      setStreamingStarted(false);
      setCallMetaData({ ...callMetaData, callId: crypto.randomUUID() });
    }
  };

  const startRecording = async () => {
    console.log(`DEBUG - [${new Date().toISOString()}]: Start Recording and Streaming Audio to Websocket server.`);

    try {
      audioContext.current = new window.AudioContext();
      displayStream.current = await window.navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      micStream.current = await window.navigator.mediaDevices.getUserMedia({ video: false, audio: true });
      SOURCE_SAMPLING_RATE = audioContext.current.sampleRate;
      callMetaData.samplingRate = SOURCE_SAMPLING_RATE;
      callMetaData.callEvent = 'START';
      console.log(`DEBUG - [${new Date().toISOString()}]: Send Call START msg: ${JSON.stringify(callMetaData)}`);
      sendMessage(JSON.stringify(callMetaData));
      setStreamingStarted(true);

      displayAudioSource.current = audioContext.current.createMediaStreamSource(displayStream.current);
      micAudioSource.current = audioContext.current.createMediaStreamSource(micStream.current);

      const monoDisplaySource = convertToMono(displayAudioSource.current);
      const monoMicSource = convertToMono(micAudioSource.current);

      channelMerger.current = audioContext.current.createChannelMerger(2);
      if (micInputOption.value === 'agent') {
        monoMicSource.connect(channelMerger.current, 0, 0);
        monoDisplaySource.connect(channelMerger.current, 0, 1);
      } else {
        monoMicSource.connect(channelMerger.current, 0, 1);
        monoDisplaySource.connect(channelMerger.current, 0, 0);
      }

      console.log(`DEBUG - [${new Date().toISOString()}]: Registering AudioWorklet processor`);
      try {
        await audioContext.current.audioWorklet.addModule('./worklets/recording-processor.js');
      } catch (error) {
        console.log(`DEBUG - [${new Date().toISOString()}]: Error registering AudioWorklet: ${error}`);
      }

      audioProcessor.current = new AudioWorkletNode(audioContext.current, 'recording-processor');
      audioProcessor.current.port.onmessageerror = (error) => console.log(`DEBUG: Error from worklet ${error}`);
      audioProcessor.current.port.onmessage = (event) => sendMessage(event.data);
      channelMerger.current.connect(audioProcessor.current);
    } catch (error) {
      alert(`An error occurred while recording: ${error}`);
      await stopRecording();
    }
  };

  async function toggleRecording() {
    if (recording) {
      await startRecording();
    } else {
      await stopRecording();
    }
  }

  useEffect(() => {
    toggleRecording();
  }, [recording]);

  const handleRecording = () => {
    if (settings.WSEndpoint) {
      setRecording(!recording);
    } else {
      alert('Enable Websocket Audio input to use this feature');
    }
    return recording;
  };

  return (
    <div className="p-6 max-w-2xl">
      <div className="border border-border rounded-lg bg-background overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Call Metadata</h2>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div className="space-y-1.5">
              <Label htmlFor="callId">Call ID</Label>
              <p className="text-xs text-muted-foreground">Auto-generated unique call ID</p>
              <Input
                id="callId"
                value={callMetaData.callId}
                onChange={handleCallIdChange}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="agentId">Agent ID</Label>
              <p className="text-xs text-muted-foreground">Agent ID</p>
              <Input
                id="agentId"
                value={callMetaData.agentId}
                onChange={handleAgentIdChange}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fromNumber">Customer Phone</Label>
              <p className="text-xs text-muted-foreground">Customer Phone</p>
              <Input
                id="fromNumber"
                value={callMetaData.fromNumber}
                onChange={handlefromNumberChange}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="toNumber">System Phone</Label>
              <p className="text-xs text-muted-foreground">System Phone</p>
              <Input
                id="toNumber"
                value={callMetaData.toNumber}
                onChange={handletoNumberChange}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="micRole">Microphone Role</Label>
              <p className="text-xs text-muted-foreground">Mic input</p>
              <select
                id="micRole"
                value={micInputOption.value}
                onChange={handleMicInputOptionSelection}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="caller">CALLER</option>
                <option value="agent">AGENT</option>
              </select>
            </div>
          </div>

          <Button onClick={handleRecording}>
            {recording ? 'Stop Streaming' : 'Start Streaming'}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default StreamAudio;
