import json
import os

def input_float(prompt, default=None):
    val = input(f"{prompt} [{default}]: ")
    return float(val) if val else default

def input_str(prompt, default=None):
    val = input(f"{prompt} [{default}]: ")
    return val if val else default

def input_int(prompt, default=None):
    val = input(f"{prompt} [{default}]: ")
    return int(val) if val else default

def create_deck_json():
    deck = {}
    deck["name"] = input_str("Deck name", "My Automation Deck")
    deck["description"] = input_str("Description", "Custom deck")
    deck["type"] = input_str("Type (e.g. SLAS Standard Labware)", "SLAS Standard Labware")
    deck["deck_offset"] = [
        input_float("Deck offset X from machine (0,0)", 0.0),
        input_float("Deck offset Y from machine (0,0)", 0.0)
    ]
    deck["material"] = {
        "deck": input_str("Deck material", ""),
        "mask": input_str("Mask material", "")
    }
    deck["slot_reference_corner"] = input_str("Slot reference corner", "bottom_left")
    deck["safe_z_clearance"] = input_float("Safe Z clearance (mm)", 10.0)

    n_slots = input_int("Number of slots", 6)
    deck["slots"] = {}

    for i in range(n_slots):
        print(f"\n--- Slot {i} ---")
        slot = {}
        slot["coordinates"] = [
            input_float(f"  Slot {i} X", 0.0),
            input_float(f"  Slot {i} Y", 0.0)
        ]
        shape = input_str("  Shape (rectangle/circle)", "rectangle")
        slot["shape"] = shape
        if shape == "rectangle":
            slot["width"] = input_float("  Width (mm)", 0.0)
            slot["length"] = input_float("  Length (mm)", 0.0)
        elif shape == "circle":
            slot["diameter"] = input_float("  Diameter (mm)", 0.0)
        # Add more shapes here if needed
        slot["has_labware"] = False
        slot["labware"] = None
        deck["slots"][str(i)] = slot

    filename = input_str("Output JSON filename", "filename.json")
    if not filename.endswith('.json'):
        filename += '.json'
    deck_def_dir = os.path.join(os.path.dirname(__file__), "deck_definition")
    os.makedirs(deck_def_dir, exist_ok=True)
    full_path = os.path.join(deck_def_dir, filename)
    if os.path.exists(full_path):
        overwrite = input(f"File '{filename}' already exists. Overwrite? (y/n) [n]: ").strip().lower()
        if overwrite not in ("y", "yes"): 
            print("Aborted: file not overwritten.")
            return
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(deck, f, indent=4, ensure_ascii=False)
    print(f"\nDeck JSON created: {full_path}")

if __name__ == "__main__":
    create_deck_json()