import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_PATH = ROOT / "data" / "documents.json"

REQUIRED_TOP_LEVEL = ["document_id", "doc_type", "source", "title", "content", "metadata"]

# Coverage floors, set with headroom below the actual extraction rates measured
# against the current corpus (MITRE 100% tactics, Sigma 89% ATT&CK mappings --
# see DECISIONS.md). Not every Sigma rule maps to a technique, so this checks
# extraction is *working*, not that every single rule has a mapping.
MIN_MITRE_TACTIC_COVERAGE = 0.95
MIN_SIGMA_MAPPING_COVERAGE = 0.50


def check_required_fields(documents):
    errors = []
    seen_ids = set()
    for i, doc in enumerate(documents):
        label = doc.get("document_id", f"index {i}")
        for field in REQUIRED_TOP_LEVEL:
            if field not in doc:
                errors.append(f"{label}: missing top-level field {field!r}")
        source = doc.get("source")
        if not isinstance(source, dict) or not source.get("name"):
            errors.append(f"{label}: source must be an object with a non-empty 'name'")
        if not isinstance(doc.get("metadata"), dict):
            errors.append(f"{label}: metadata must be an object")
        doc_id = doc.get("document_id")
        if doc_id in seen_ids:
            errors.append(f"duplicate document_id: {doc_id!r}")
        seen_ids.add(doc_id)
    return errors


def check_mitre_tactics(documents):
    mitre_docs = [d for d in documents if d.get("doc_type") == "attack_technique"]
    if not mitre_docs:
        return ["no attack_technique documents found"], 0, 0
    with_tactics = [d for d in mitre_docs if d.get("metadata", {}).get("tactics")]
    coverage = len(with_tactics) / len(mitre_docs)
    errors = []
    if coverage < MIN_MITRE_TACTIC_COVERAGE:
        errors.append(
            f"only {coverage:.1%} of {len(mitre_docs)} attack_technique docs have "
            f"non-empty metadata.tactics (expected >= {MIN_MITRE_TACTIC_COVERAGE:.0%})"
        )
    return errors, len(mitre_docs), len(with_tactics)


def check_sigma_attack_mappings(documents):
    sigma_docs = [d for d in documents if d.get("doc_type") == "detection_rule"]
    if not sigma_docs:
        return ["no detection_rule documents found"], 0, 0
    with_mappings = [d for d in sigma_docs if d.get("metadata", {}).get("attack_techniques")]
    coverage = len(with_mappings) / len(sigma_docs)
    errors = []
    if coverage < MIN_SIGMA_MAPPING_COVERAGE:
        errors.append(
            f"only {coverage:.1%} of {len(sigma_docs)} detection_rule docs have non-empty "
            f"metadata.attack_techniques (expected >= {MIN_SIGMA_MAPPING_COVERAGE:.0%}) "
            f"-- ATT&CK tag extraction may be broken"
        )
    return errors, len(sigma_docs), len(with_mappings)


def main():
    documents = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
    errors = []

    errors += check_required_fields(documents)

    tactic_errors, mitre_total, mitre_with_tactics = check_mitre_tactics(documents)
    errors += tactic_errors

    mapping_errors, sigma_total, sigma_with_mappings = check_sigma_attack_mappings(documents)
    errors += mapping_errors

    print(f"documents: {len(documents)}")
    if mitre_total:
        print(f"attack_technique docs with tactics extracted: {mitre_with_tactics}/{mitre_total} ({mitre_with_tactics/mitre_total:.1%})")
    if sigma_total:
        print(f"detection_rule docs with ATT&CK technique mappings extracted: {sigma_with_mappings}/{sigma_total} ({sigma_with_mappings/sigma_total:.1%})")

    if errors:
        print(f"\n{len(errors)} validation error(s):")
        for e in errors[:50]:
            print(f"  - {e}")
        sys.exit(1)

    print("\nall checks passed")


if __name__ == "__main__":
    main()
