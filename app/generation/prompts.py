SYSTEM_PROMPT = """You are a security assistant. Answer the user's question using ONLY the evidence documents provided below. Do not use outside knowledge, and do not infer beyond what the evidence directly states.

Break your answer into a list of atomic claims. Each claim must cite the document_id(s) it is directly supported by. Cite only document_ids from the evidence list -- never fabricate a document_id, and never cite a document for a claim it does not actually support.

If the evidence is insufficient to fully answer the question, set "insufficient_evidence" to true and include only the claims that ARE supported by the evidence -- do not pad the answer with unsupported claims to seem more complete.

Respond with ONLY a JSON object in this exact shape, no other text before or after it:
{"claims": [{"text": "...", "cited_document_ids": ["..."]}], "insufficient_evidence": false}"""

# Used when the groundedness judge rejects the first attempt -- names the specific
# claims that failed so the retry can fix or drop them, rather than regenerating blind.
STRICT_RETRY_SUFFIX = """

Your previous answer included claims that were not actually supported by their cited evidence:
{failed_claims}

Try again. For each of those, either find real support elsewhere in the evidence and cite that instead, or drop the claim entirely. Do not repeat an unsupported claim."""


def format_evidence(documents):
    """Render retrieved documents into the block the model sees. `documents` is a list
    of dicts with at least "document_id", "title", "content" (or "content_excerpt").
    """
    blocks = []
    for doc in documents:
        content = doc.get("content") or doc.get("content_excerpt") or ""
        blocks.append(f"[{doc['document_id']}] {doc['title']}\n{content}")
    return "\n\n".join(blocks)


def build_user_prompt(query, documents, failed_claims=None):
    prompt = f"Question: {query}\n\nEvidence:\n{format_evidence(documents)}"
    if failed_claims:
        failed_text = "\n".join(f"- {c!r} (cited {ids!r})" for c, ids in failed_claims)
        prompt += STRICT_RETRY_SUFFIX.format(failed_claims=failed_text)
    return prompt
