import boto3, json, time, glob, os

import boto3.session
session = boto3.session.Session(profile_name='dev')
transcribe = session.client('transcribe', region_name='us-east-1')
s3_client = session.client('s3', region_name='us-east-1')
s3_bucket = "agent-copilot-dev-recordingsbucket-fikuwc9oggyj"

def transcribe_file(filepath: str) -> dict:
    filename = os.path.basename(filepath)
    job_name = f"benchmark-{filename.replace('.wav','')}-{int(time.time())}"
    s3_key = f"benchmark-audio-transcribe/{filename}"

    start = time.time()
    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={'MediaFileUri': f"s3://{s3_bucket}/{s3_key}"},
        MediaFormat='wav',
        LanguageCode='es-US',
        Settings={'ShowSpeakerLabels': True, 'MaxSpeakerLabels': 2}
    )

    # Polling hasta que termine
    while True:
        response = transcribe.get_transcription_job(TranscriptionJobName=job_name)
        status = response['TranscriptionJob']['TranscriptionJobStatus']
        if status in ('COMPLETED', 'FAILED'):
            break
        time.sleep(3)

    latency = time.time() - start

    if status == 'FAILED':
        return {"file": filename, "error": "FAILED", "latency_seconds": round(latency, 2)}

    # Bajar el resultado
    import urllib.request
    result_url = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
    with urllib.request.urlopen(result_url) as r:
        result = json.loads(r.read())

    transcript = result['results']['transcripts'][0]['transcript']
    items = result['results'].get('items', [])
    speakers = set(i.get('speaker_label','') for i in items if i.get('speaker_label'))

    return {
        "file": filename,
        "transcript": transcript,
        "word_count": len(transcript.split()),
        "latency_seconds": round(latency, 2),
        "speakers_detected": list(speakers),
    }

files = sorted(glob.glob("deepgram-test-benchmark-audio/*.wav"))
print(f"Found {len(files)} files\n")
results = []

for f in files:
    print(f"Processing {os.path.basename(f)}...")
    try:
        r = transcribe_file(f)
        results.append(r)
        print(f"  ✓ {r.get('word_count','?')} words, {r['latency_seconds']}s")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        results.append({"file": os.path.basename(f), "error": str(e)})

with open("transcribe_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\nDone. Results in transcribe_results.json")
successful = [r for r in results if "transcript" in r]
if successful:
    avg = sum(r['latency_seconds'] for r in successful) / len(successful)
    print(f"Avg latency: {avg:.1f}s | Successful: {len(successful)}/{len(files)}")
