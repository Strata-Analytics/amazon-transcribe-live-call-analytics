// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useRef, useState } from 'react';
import { Logger } from 'aws-amplify';
import { Pause, Play, Volume2, VolumeX } from 'lucide-react';

import useAppContext from '../../contexts/app';
import generateS3PresignedUrl from '../common/generate-s3-presigned-url';

const logger = new Logger('RecordingPlayer');

const formatTime = (secs) => {
  if (!secs || Number.isNaN(secs)) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
};

const AudioPlayer = ({ src }) => {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);

  const toggle = () => {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setPlaying(!playing);
  };

  const handleTimeUpdate = () => setCurrentTime(audioRef.current?.currentTime ?? 0);
  const handleLoadedMetadata = () => setDuration(audioRef.current?.duration ?? 0);
  const handleEnded = () => setPlaying(false);

  const handleSeek = (e) => {
    if (!audioRef.current || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    audioRef.current.currentTime = ratio * duration;
    setCurrentTime(audioRef.current.currentTime);
  };

  const toggleMute = () => {
    if (!audioRef.current) return;
    audioRef.current.muted = !muted;
    setMuted(!muted);
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-muted/30 w-full">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        ref={audioRef}
        src={src}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={handleEnded}
      />

      {/* Play / Pause */}
      <button
        type="button"
        onClick={toggle}
        className="flex-none flex items-center justify-center h-7 w-7 rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
        aria-label={playing ? 'Pause' : 'Play'}
      >
        {playing
          ? <Pause className="h-3.5 w-3.5 fill-white" />
          : <Play className="h-3.5 w-3.5 fill-white ml-0.5" />}
      </button>

      {/* Progress bar */}
      <div className="flex-1 flex flex-col gap-0.5">
        <div
          className="relative h-1.5 bg-border rounded-full cursor-pointer group"
          onClick={handleSeek}
          role="slider"
          aria-label="Seek"
          aria-valuenow={Math.round(progress)}
          aria-valuemin={0}
          aria-valuemax={100}
          tabIndex={0}
          onKeyDown={(e) => {
            if (!audioRef.current) return;
            if (e.key === 'ArrowRight') audioRef.current.currentTime = Math.min(duration, currentTime + 5);
            if (e.key === 'ArrowLeft') audioRef.current.currentTime = Math.max(0, currentTime - 5);
          }}
        >
          <div
            className="h-full bg-primary rounded-full transition-[width] duration-100"
            style={{ width: `${progress}%` }}
          />
          <div
            className="absolute top-1/2 -translate-y-1/2 h-3 w-3 rounded-full bg-primary shadow opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ left: `calc(${progress}% - 6px)` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground leading-none">
          <span>{formatTime(currentTime)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      </div>

      {/* Mute */}
      <button
        type="button"
        onClick={toggleMute}
        className="flex-none text-muted-foreground hover:text-foreground transition-colors"
        aria-label={muted ? 'Unmute' : 'Mute'}
      >
        {muted
          ? <VolumeX className="h-4 w-4" />
          : <Volume2 className="h-4 w-4" />}
      </button>
    </div>
  );
};

/* eslint-disable react/prop-types */
export const RecordingPlayer = ({ recordingUrl }) => {
  const [preSignedUrl, setPreSignedUrl] = useState();
  const { setErrorMessage, currentCredentials } = useAppContext();

  useEffect(() => {
    if (recordingUrl) {
      (async () => {
        logger.debug('recording url to presign', recordingUrl);
        try {
          const url = await generateS3PresignedUrl(recordingUrl, currentCredentials);
          logger.debug('recording presigned url', url);
          setPreSignedUrl(url);
        } catch (error) {
          setErrorMessage('failed to get recording url - please try again later');
          logger.error('failed generate recording s3 url', error);
        }
      })();
    }
  }, [recordingUrl, currentCredentials]);

  return preSignedUrl?.length ? <AudioPlayer src={preSignedUrl} /> : null;
};

export default RecordingPlayer;
