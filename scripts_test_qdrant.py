from qdrant_client import QdrantClient

client = QdrantClient(
    url="https://daf7ffca-c51c-4bc9-945d-e25927dd4d5e.eu-central-1-0.aws.cloud.qdrant.io",
    api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6MjIwYzgzMGYtNDJiNS00NjdjLTljZjgtYTcxMTNmYzNmYjczIn0.3K1rhQXdg-18Et8iCLyXq9IuaLe6kDioZuz2hR9iOQs",
)

for col in client.get_collections().collections:
    print(f"=== {col.name} ===")
    points, _ = client.scroll(
        collection_name=col.name,
        limit=3,
        with_payload=True,
        with_vectors=False,
    )
    for i, p in enumerate(points):
        print(f"  Point {i+1}:")
        print(f"    ID: {p.id}")
        print(f"    Payload keys: {sorted(p.payload.keys())}")
        
        # Check ALL values
        for k, v in sorted(p.payload.items()):
            if v is None:
                continue
            v_str = str(v)
            if len(v_str) > 200:
                print(f"    {k}: [{len(v_str)} chars] {v_str[:200]}...")
            else:
                print(f"    {k}: {v_str}")
        print()
    print()
