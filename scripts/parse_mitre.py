import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "enterprise-attack.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "documents.json"
SOURCE = "MITRE ATT&CK"


def extract_attack_id(obj):
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
            return ref["external_id"]
    return None


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    documents = []
    for obj in bundle["objects"]:
        if obj.get("type") != "attack-pattern":
            continue
        attack_id = extract_attack_id(obj)
        if not attack_id:
            continue
        documents.append(
            {
                "id": attack_id,
                "title": obj.get("name", ""),
                "content": obj.get("description", ""),
                "source": SOURCE,
            }
        )

    documents.sort(key=lambda d: d["id"])

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"wrote {len(documents)} documents -> {OUT_PATH}")


if __name__ == "__main__":
    main()
