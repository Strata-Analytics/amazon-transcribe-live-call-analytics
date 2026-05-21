import os, json, time, glob
import requests

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")

def transcribe_deepgram(filepath: str) -> dict:
    with open(filepath, "rb") as f:
        audio_data = f.read()
    
    url = "https://api.deepgram.com/v1/listen"
    params = {
        "model": "nova-2",
        "language": "es-419",
        "diarize": "true",
        "punctuate": "true",
        "utterances": "true",
    }
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav",
    }
    
    start = time.time()
    response = requests.post(url, params=params, headers=headers, data=audio_data)
    latency = time.time() - start
    
    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
    
    result = response.json()
    transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
    utterances = result.get("results", {}).get("utterances", [])
    
    return {
        "file": os.path.basename(filepath),
        "transcript": transcript,
        "utterances": utterances,
        "latency_seconds": round(latency, 2),
        "word_count": len(transcript.split()),
    }

def main():
    files = sorted(glob.glob("deepgram-test-benchmark-audio/*.wav"))
    print(f"Found {len(files)} files\n")
    results = []
    
    for f in files:
        print(f"Processing {os.path.basename(f)}...")
        try:
            result = transcribe_deepgram(f)
            results.append(result)
            print(f"  ✓ {result['word_count']} words, {result['latency_seconds']}s, {len(result['utterances'])} utterances")
            print(f"  Preview: {result['transcript'][:100]}...")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append({"file": os.path.basename(f), "error": str(e)})
    
    with open("deepgram-test-benchmark-audio/deepgram_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to deepgram_results.json")
    successful = [r for r in results if "transcript" in r]
    if successful:
        avg_latency = sum(r["latency_seconds"] for r in successful) / len(successful)
        print(f"\nSummary:")
        print(f"  Successful: {len(successful)}/{len(files)}")
        print(f"  Avg latency: {avg_latency:.2f}s")
        print(f"  Min latency: {min(r['latency_seconds'] for r in successful)}s")
        print(f"  Max latency: {max(r['latency_seconds'] for r in successful)}s")

main()
