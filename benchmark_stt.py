import os, json, time, glob, asyncio
from deepgram import DeepgramClient

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")

async def transcribe_deepgram(filepath: str) -> dict:
    client = DeepgramClient(DEEPGRAM_API_KEY)
    with open(filepath, "rb") as f:
        audio_data = f.read()
    options = {
        "model": "nova-2",
        "language": "es-419",
        "diarize": True,
        "punctuate": True,
        "utterances": True,
    }
    start = time.time()
    response = await client.listen.asyncrest.v("1").transcribe_file(
        {"buffer": audio_data, "mimetype": "audio/wav"},
        options
    )
    latency = time.time() - start
    result = response.to_dict()
    transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
    utterances = result.get("results", {}).get("utterances", [])
    return {
        "file": os.path.basename(filepath),
        "transcript": transcript,
        "utterances": utterances,
        "latency_seconds": round(latency, 2),
        "word_count": len(transcript.split()),
    }

async def main():
    files = sorted(glob.glob("benchmark-audio/*.wav"))
    print(f"Found {len(files)} files\n")
    results = []
    for f in files:
        print(f"Processing {os.path.basename(f)}...")
        try:
            result = await transcribe_deepgram(f)
            results.append(result)
            print(f"  ✓ {result['word_count']} words, {result['latency_seconds']}s, {len(result['utterances'])} utterances")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append({"file": os.path.basename(f), "error": str(e)})
    with open("deepgram_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to deepgram_results.json")
    successful = [r for r in results if "transcript" in r]
    if successful:
        avg_latency = sum(r["latency_seconds"] for r in successful) / len(successful)
        print(f"Average latency: {avg_latency:.2f}s")
        print(f"Successful: {len(successful)}/{len(files)}")

asyncio.run(main())
