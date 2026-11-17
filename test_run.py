# test_run.py
with open("hermes_core.py", "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

print(f">>> hermes_core.py ma {len(lines)} linii. Oto kluczowe linie:")
for i, line in enumerate(lines):
    if any(k in line.lower() for k in ["post", "url", "neobus", "headers", "requests"]):
        print(f"L{i+1}: {line.strip()}")
