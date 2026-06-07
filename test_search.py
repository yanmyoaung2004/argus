from duckduckgo_search import DDGS
with DDGS() as ddgs:
    results = list(ddgs.text("what is python used for", max_results=5))
print(f"Results count: {len(results)}")
for r in results:
    print(f"  - {r.get('title', '')[:80]}  |  {r.get('href', '')[:80]}")
