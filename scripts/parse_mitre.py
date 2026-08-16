import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "enterprise-attack.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "documents.json"
SOURCE_NAME = "MITRE ATT&CK"
DOC_TYPE = "attack_technique"


def extract_attack_id(obj):
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
            return ref["external_id"]
    return None


def extract_url(obj):
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("url"):
            return ref["url"]
    return None


def extract_tactics(obj):
    return sorted(
        {
            phase["phase_name"]
            for phase in obj.get("kill_chain_phases", [])
            if phase.get("kill_chain_name") == "mitre-attack" and phase.get("phase_name")
        }
    )


def extract_parent_technique_id(technique_id):
    return technique_id.split(".")[0] if "." in technique_id else None


def build_document(obj, technique_id):
    return {
        "document_id": f"mitre_attack:{technique_id}",
        "doc_type": DOC_TYPE,
        "source": {"name": SOURCE_NAME, "url": extract_url(obj)},
        "title": obj.get("name", ""),
        "content": obj.get("description", ""),
        "metadata": {
            "technique_id": technique_id,
            "is_subtechnique": bool(obj.get("x_mitre_is_subtechnique", False)),
            "parent_technique_id": extract_parent_technique_id(technique_id),
            "tactics": extract_tactics(obj),
            "platforms": obj.get("x_mitre_platforms", []),
            "stix_id": obj.get("id"),
        },
    }


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    documents = []
    for obj in bundle["objects"]:
        if obj.get("type") != "attack-pattern":
            continue
        technique_id = extract_attack_id(obj)
        if not technique_id:
            continue
        documents.append(build_document(obj, technique_id))

    documents.sort(key=lambda d: d["metadata"]["technique_id"])

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"wrote {len(documents)} documents -> {OUT_PATH}")


if __name__ == "__main__":
    main()
