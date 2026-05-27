"""
streaming_benchmark.py
Simulates real-time streaming from WAV files and measures latency for both
Deepgram and AWS Transcribe streaming APIs.

Metrics per file:
  first_interim_ms      : ms from audio start → first partial word
  first_final_ms        : ms from audio start → first finalized transcript
  avg_finalization_ms   : avg ms from last audio chunk → final transcript
  transcript            : full final text
  word_count            : words in final transcript

Usage:
  python3 streaming_benchmark.py [folder]
  python3 streaming_benchmark.py deepgram-test-benchmark-audio/2026-05-26
"""

import asyncio, glob, json, os, sys, time, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK_MS = 100  # send 100ms of audio per chunk


# ── Credentials ───────────────────────────────────────────────────────────────

def load_deepgram_key():
    key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        env_file = os.path.join(HERE, ".env")
        if os.path.exists(env_file):
            for line in open(env_file):
                if line.startswith("DEEPGRAM_API_KEY"):
                    key = line.strip().split("=", 1)[1].strip().strip('"')
    return key


def make_aws_session():
    import boto3.session
    try:
        s = boto3.session.Session(profile_name='dev')
        s.client('sts', region_name='us-east-1').get_caller_identity()
        return s
    except Exception:
        creds = json.loads(__import__('subprocess').check_output(
            ['aws', 'configure', 'export-credentials', '--profile', 'dev', '--format', 'process']
        ))
        return boto3.session.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken'],
        )


# ── Audio helpers ─────────────────────────────────────────────────────────────

def load_wav_mono_pcm(filepath):
    """Read WAV, downmix to mono int16, return (pcm_bytes, sample_rate)."""
    with wave.open(filepath, 'rb') as wf:
        n_channels  = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth   = wf.getsampwidth()
        raw         = wf.readframes(wf.getnframes())

    dtype   = np.int16 if sampwidth == 2 else np.int32
    samples = np.frombuffer(raw, dtype=dtype)
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1).astype(np.int16)

    return samples.tobytes(), sample_rate


def iter_chunks(pcm_bytes, sample_rate, chunk_ms=CHUNK_MS):
    """Yield (chunk_bytes, duration_s) slices."""
    n = int(sample_rate * chunk_ms / 1000) * 2  # 2 bytes per int16 sample
    dur = chunk_ms / 1000.0
    for i in range(0, len(pcm_bytes), n):
        yield pcm_bytes[i:i + n], dur


# ── Deepgram streaming ────────────────────────────────────────────────────────

async def run_deepgram(pcm_bytes, sample_rate, api_key):
    from deepgram import AsyncDeepgramClient
    from deepgram.listen.v1.types import ListenV1Results
    from deepgram.core.events import EventType

    client = AsyncDeepgramClient(api_key=api_key)

    t0               = [None]
    first_interim_ms = [None]
    first_final_ms   = [None]
    fin_delays       = []
    last_audio_ts    = [None]
    transcript_parts = []

    async with client.listen.v1.connect(
        model           = "nova-2",
        language        = "es-419",
        punctuate       = True,
        interim_results = True,
        endpointing     = 300,
        encoding        = "linear16",
        sample_rate     = sample_rate,
        channels        = 1,
    ) as conn:
        t0[0] = time.time()

        def on_message(event):
            if not isinstance(event, ListenV1Results):
                return
            alts = event.channel.alternatives if event.channel else []
            text = alts[0].transcript if alts else ""
            if not text:
                return
            ts = time.time()
            if first_interim_ms[0] is None:
                first_interim_ms[0] = round((ts - t0[0]) * 1000)
            if event.is_final:
                if first_final_ms[0] is None:
                    first_final_ms[0] = round((ts - t0[0]) * 1000)
                if last_audio_ts[0]:
                    fin_delays.append(round((ts - last_audio_ts[0]) * 1000))
                transcript_parts.append(text)

        conn.on(EventType.MESSAGE, on_message)

        async def send_loop():
            for chunk, dur in iter_chunks(pcm_bytes, sample_rate):
                await conn.send_media(chunk)
                last_audio_ts[0] = time.time()
                await asyncio.sleep(dur)
            await conn.send_close_stream()

        await asyncio.gather(send_loop(), conn.start_listening())

    transcript = " ".join(transcript_parts)
    return {
        "first_interim_ms":    first_interim_ms[0],
        "first_final_ms":      first_final_ms[0],
        "avg_finalization_ms": round(sum(fin_delays) / len(fin_delays)) if fin_delays else None,
        "transcript":          transcript,
        "word_count":          len(transcript.split()),
    }


# ── AWS Transcribe streaming ──────────────────────────────────────────────────

async def run_transcribe(pcm_bytes, sample_rate, aws_session):
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.handlers import TranscriptResultStreamHandler
    from amazon_transcribe.model import TranscriptEvent
    from amazon_transcribe.auth import StaticCredentialResolver

    frozen = aws_session.get_credentials().get_frozen_credentials()
    cred_resolver = StaticCredentialResolver(
        access_key_id     = frozen.access_key,
        secret_access_key = frozen.secret_key,
        session_token     = frozen.token,
    )

    client = TranscribeStreamingClient(
        region             = "us-east-1",
        credential_resolver = cred_resolver,
    )

    stream = await client.start_stream_transcription(
        language_code                        = "es-US",
        media_sample_rate_hz                 = sample_rate,
        media_encoding                       = "pcm",
        enable_partial_results_stabilization = True,
        partial_results_stability            = "high",
    )

    t0               = time.time()
    first_interim_ms = None
    first_final_ms   = None
    fin_delays       = []
    last_audio_ts    = [None]
    transcript_parts = []

    class Handler(TranscriptResultStreamHandler):
        async def handle_transcript_event(self, event: TranscriptEvent):
            nonlocal first_interim_ms, first_final_ms
            ts = time.time()
            for result in event.transcript.results:
                alts = result.alternatives
                if not alts or not alts[0].transcript:
                    continue
                if first_interim_ms is None:
                    first_interim_ms = round((ts - t0) * 1000)
                if not result.is_partial:
                    if first_final_ms is None:
                        first_final_ms = round((ts - t0) * 1000)
                    if last_audio_ts[0]:
                        fin_delays.append(round((ts - last_audio_ts[0]) * 1000))
                    transcript_parts.append(alts[0].transcript)

    handler = Handler(stream.output_stream)

    async def send_loop():
        for chunk, dur in iter_chunks(pcm_bytes, sample_rate):
            await stream.input_stream.send_audio_event(audio_chunk=chunk)
            last_audio_ts[0] = time.time()
            await asyncio.sleep(dur)
        await stream.input_stream.end_stream()

    await asyncio.gather(send_loop(), handler.handle_events())

    transcript = " ".join(transcript_parts)
    return {
        "first_interim_ms":    first_interim_ms,
        "first_final_ms":      first_final_ms,
        "avg_finalization_ms": round(sum(fin_delays) / len(fin_delays)) if fin_delays else None,
        "transcript":          transcript,
        "word_count":          len(transcript.split()),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else HERE
    folder = os.path.abspath(folder.rstrip("/"))
    tag    = os.path.basename(folder)
    files  = sorted(glob.glob(os.path.join(folder, "*.wav")))

    if not files:
        print(f"No WAV files found in {folder}")
        return

    print(f"Found {len(files)} files in {folder}\n")

    api_key     = load_deepgram_key()
    aws_session = make_aws_session()
    results     = []

    def fmt(v):
        return f"{v}ms" if v is not None else "—"

    for filepath in files:
        fname = os.path.basename(filepath)
        print(f"Processing {fname}...")
        pcm_bytes, sample_rate = load_wav_mono_pcm(filepath)
        result = {"file": fname}

        try:
            print("  [Deepgram] streaming...", end=" ", flush=True)
            dg = await run_deepgram(pcm_bytes, sample_rate, api_key)
            result["deepgram"] = dg
            print(f"first_interim={fmt(dg['first_interim_ms'])}  "
                  f"first_final={fmt(dg['first_final_ms'])}  "
                  f"avg_fin={fmt(dg['avg_finalization_ms'])}  "
                  f"words={dg['word_count']}")
        except Exception as e:
            result["deepgram"] = {"error": str(e)}
            print(f"ERROR: {e}")

        try:
            print("  [Transcribe] streaming...", end=" ", flush=True)
            tr = await run_transcribe(pcm_bytes, sample_rate, aws_session)
            result["transcribe"] = tr
            print(f"first_interim={fmt(tr['first_interim_ms'])}  "
                  f"first_final={fmt(tr['first_final_ms'])}  "
                  f"avg_fin={fmt(tr['avg_finalization_ms'])}  "
                  f"words={tr['word_count']}")
        except Exception as e:
            result["transcribe"] = {"error": str(e)}
            print(f"ERROR: {e}")

        results.append(result)
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    col = 14
    print("=" * 85)
    print(f"{'File':<10} {'DG 1st int':>{col}} {'DG 1st fin':>{col}} {'DG avg fin':>{col}} "
          f"{'TR 1st int':>{col}} {'TR 1st fin':>{col}} {'TR avg fin':>{col}}")
    print("-" * 85)
    for r in results:
        dg = r.get("deepgram", {})
        tr = r.get("transcribe", {})
        print(f"{r['file'][:8]:<10} "
              f"{fmt(dg.get('first_interim_ms')):>{col}} "
              f"{fmt(dg.get('first_final_ms')):>{col}} "
              f"{fmt(dg.get('avg_finalization_ms')):>{col}} "
              f"{fmt(tr.get('first_interim_ms')):>{col}} "
              f"{fmt(tr.get('first_final_ms')):>{col}} "
              f"{fmt(tr.get('avg_finalization_ms')):>{col}}")
    print("=" * 85)

    out = os.path.join(HERE, f"streaming_results_{tag}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
