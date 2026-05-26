with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("--- Searching for 'session' in App.tsx ---")
count = 0
for idx, line in enumerate(lines):
    if 'session' in line.lower():
        print(f"Line {idx+1}: {line.strip()}")
        count += 1
        if count > 40:
            print("Truncated...")
            break
