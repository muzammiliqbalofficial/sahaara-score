"""Quick timing of list endpoint."""
import time
import urllib.request

# Cold request (first after idle).
start = time.time()
r = urllib.request.urlopen("http://localhost:8000/api/v1/review/applicants?limit=50")
data = r.read()
elapsed = time.time() - start
print(f"Request #1 (cold): {elapsed*1000:.0f}ms ({len(data)} bytes)")

# Warm requests.
for i in range(3):
    start = time.time()
    r = urllib.request.urlopen("http://localhost:8000/api/v1/review/applicants?limit=50")
    data = r.read()
    elapsed = time.time() - start
    print(f"Request #{i+2} (warm): {elapsed*1000:.0f}ms ({len(data)} bytes)")
