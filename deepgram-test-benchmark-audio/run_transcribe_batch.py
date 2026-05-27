import boto3, json, time, glob, os

import boto3.session


def make_session():
    try:
        s = boto3.session.Session(profile_name='dev')
        s.client('sts', region_name='us-east-1').get_caller_identity()
        return s
    except Exception:
        import subprocess
        creds = json.loads(subprocess.check_output(
            ['aws', 'configure', 'export-credentials', '--profile', 'dev', '--format', 'process']
        ))
        return boto3.session.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken'],
        )


session = make_session()
transcribe = session.client('transcribe', region_name='us-east-1')
s3_client = session.client('s3', region_name='us-east-1')
s3_bucket = "agent-copilot-dev-recordingsbucket-fikuwc9oggyj"


def transcribe_file(filepath: str) -> dict:
    filename = os.path.basename(filepath)
    job_name = f"benchmark-{filename.replace('.wav','')}-{int(time.time())}"
    s3_key = f"benchmark-audio-transcribe/{filename}"

    print(f"  Uploading {filename} to S3...")
    s3_client.upload_file(filepath, s3_bucket, s3_key)

    start = time.time()
    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={'MediaFileUri': f"s3://{s3_bucket}/{s3_key}"},
        MediaFormat='wav',
        LanguageCode='es-US',
        Settings={'ShowSpeakerLabels': True, 'MaxSpeakerLabels': 2}
    )

    while True:
        response = transcribe.get_transcription_job(TranscriptionJobName=job_name)
        status = response['TranscriptionJob']['TranscriptionJobStatus']
        if status in ('COMPLETED', 'FAILED'):
            break
        time.sleep(3)

    latency = time.time() - start

    if status == 'FAILED':
        return {"file": filename, "error": "FAILED", "latency_seconds": round(latency, 2)}

    import urllib.request
    result_url = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
    with urllib.request.urlopen(result_url) as r:
        result = json.loads(r.read())

    transcript = result['results']['transcripts'][0]['transcript']
    items = result['results'].get('items', [])
    speakers = set(i.get('speaker_label', '') for i in items if i.get('speaker_label'))

    return {
        "file": filename,
        "transcript": transcript,
        "word_count": len(transcript.split()),
        "latency_seconds": round(latency, 2),
        "speakers_detected": list(speakers),
    }


import sys
script_dir = os.path.dirname(os.path.abspath(__file__))
folder = sys.argv[1] if len(sys.argv) > 1 else script_dir
folder = os.path.abspath(folder.rstrip("/"))
tag = os.path.basename(folder)
out_file = os.path.join(script_dir, f"transcribe_results_{tag}.json")

files = sorted(glob.glob(os.path.join(folder, "*.wav")))
print(f"Found {len(files)} files in {folder}\n")
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

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nDone. Results in {out_file}")
successful = [r for r in results if "transcript" in r]
if successful:
    avg = sum(r['latency_seconds'] for r in successful) / len(successful)
    print(f"Avg latency: {avg:.1f}s | Successful: {len(successful)}/{len(files)}")
