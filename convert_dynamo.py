import json, sys, os

with open(sys.argv[1]) as f:
    data = json.load(f)

table_name = sys.argv[2]
items = data['Items']
batch_size = 25

for i in range(0, len(items), batch_size):
    batch = items[i:i+batch_size]
    request = {
        table_name: [{"PutRequest": {"Item": item}} for item in batch]
    }
    filename = f"batch_{table_name}_{i}.json"
    with open(filename, "w") as f:
        json.dump(request, f)
    print(f"Wrote {filename} ({len(batch)} items)")
