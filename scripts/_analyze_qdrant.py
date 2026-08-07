import sys, warnings
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333", prefer_grpc=False)

# 1. Collections overview
collections = [c.name for c in client.get_collections().collections]
print("=== Collections ===")
for col in sorted(collections):
    count = client.count(col, exact=True)
    print(f"  {col}: {count.count} points")

# 2. Analyze vivu_product_info content
print("\n=== vivu_product_info — chunk quality ===")
results = client.scroll("vivu_product_info", limit=2000, with_payload=True, with_vectors=False)

by_model = {}
empty_text = 0
short_text = 0
total = 0
has_numbers = 0

for point in results[0]:
    total += 1
    text = point.payload.get("text", "")
    mid = point.payload.get("model_id", "unknown")
    
    if not text.strip():
        empty_text += 1
    elif len(text.strip()) < 30:
        short_text += 1
    
    if any(kw in text for kw in ["kW", "Nm", "kWh", "VNĐ", "triệu"]):
        has_numbers += 1
    
    if mid not in by_model:
        by_model[mid] = 0
    by_model[mid] += 1

print(f"  Total: {total}")
print(f"  Empty text: {empty_text}")
print(f"  Short text (<30 chars): {short_text}")
print(f"  Has numbers (kW/Nm/kWh/VNĐ): {has_numbers}")
print(f"  By model:")
for m, c in sorted(by_model.items(), key=lambda x: -x[1]):
    print(f"    {m}: {c} chunks")

# 3. Show sample chunks per model
print("\n=== Sample chunks per model ===")
for mid in sorted(by_model.keys()):
    if by_model[mid] < 3:
        continue
    print(f"\n  [{mid}] (showing first 3):")
    count = 0
    for point in results[0]:
        if point.payload.get("model_id") == mid and count < 3:
            text = point.payload.get("text", "")[:120]
            stype = point.payload.get("source_type", "")
            print(f"    [{stype}] {text}")
            count += 1

# 4. Check vivu_specs
print("\n=== vivu_specs — sample ===")
results2 = client.scroll("vivu_specs", limit=5, with_payload=True, with_vectors=False)
for point in results2[0]:
    text = point.payload.get("text", "")[:150]
    mid = point.payload.get("model_id", "")
    print(f"  [{mid}] {text}")

# 5. Check vivu_policy
print("\n=== vivu_policy — sample ===")
results3 = client.scroll("vivu_policy", limit=3, with_payload=True, with_vectors=False)
for point in results3[0]:
    text = point.payload.get("text", "")[:150]
    print(f"  {text}")

# 6. Check vivu_maintenance
print("\n=== vivu_maintenance — sample ===")
results4 = client.scroll("vivu_maintenance", limit=3, with_payload=True, with_vectors=False)
for point in results4[0]:
    text = point.payload.get("text", "")[:150]
    print(f"  {text}")
