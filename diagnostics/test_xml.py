import xml.etree.ElementTree as ET
from pathlib import Path

# Absolute path to your toolkit backup file
target_file = Path(r"C:\Development\HomeAutomation_G1\CBUS_Extracted_Config\WATSON.xml")

print(f"=== CLIPSAL XML STRUCTURAL DIAGNOSTIC ===")
print(f"Checking file existence: {target_file.exists()}")

if not target_file.exists():
    print("[FAIL] Python cannot find the file at this location. Verify file extension matches.")
    exit()

try:
    tree = ET.parse(target_file)
    root = tree.getroot()
    print(f"[OK] XML syntax is valid. Root Tag element is: '{root.tag}'")

    # Let's inspect the first 20 elements to see exact casing
    print("\n--- Raw Tag Schema Discovery ---")
    tags_seen = set()
    for elem in root.iter():
        tags_seen.add(elem.tag)
        if len(tags_seen) >= 20:
            break
    print(f"Tags found in your XML structure: {list(tags_seen)}")

    # Test case-insensitive tree finders
    print("\n--- Query Matching Tests ---")
    print(f"Matches for './/App': {len(root.findall('.//App'))}")
    print(f"Matches for './/app': {len(root.findall('.//app'))}")
    print(f"Matches for './/Group': {len(root.findall('.//Group'))}")
    print(f"Matches for './/group': {len(root.findall('.//group'))}")

except Exception as e:
    print(f"[CRITICAL ERROR] Failed parsing your XML layout: {e}")
