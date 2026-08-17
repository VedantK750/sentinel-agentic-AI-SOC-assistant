import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from .prompts import SYSTEM_PROMPT, build_user_prompt

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT / ".env")

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-flash")

# The endpoint is a reasoning model that writes hidden "reasoning_content" tokens
# before the visible answer, billed against the same completion budget -- a request
# capped at a few hundred tokens can exhaust itself on reasoning and return truncated
# JSON (finish_reason="length") with empty/partial `content`. Verified empirically:
# max_tokens=100 truncated a two-line JSON reply after ~97 reasoning tokens; 1000+
# leaves enough room. See DECISIONS.md.
MAX_TOKENS = 2048


class Claim(BaseModel):
    text: str
    cited_document_ids: list[str]


class GeneratedAnswer(BaseModel):
    claims: list[Claim]
    insufficient_evidence: bool


class Generator:
    """Citation-grounded answer generation (PLAN §14/§15): given a query and a set of
    retrieved documents, produce a list of atomic claims, each citing the document(s)
    it's based on. Structured output (not free-text parsing) is the point -- it's what
    makes per-claim groundedness checking possible without a fragile sentence-splitting
    step. See DECISIONS.md for why this endpoint specifically needs a generous
    max_tokens and why response_format is used instead of a stricter schema mode.
    """

    def __init__(self, model=DEFAULT_MODEL):
        self.client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ["LLM_ENDPOINT"],
        )
        self.model = model

    def generate(self, query, documents, failed_claims=None) -> Optional[GeneratedAnswer]:
        """Returns None if the model's response isn't valid JSON matching the schema --
        callers should treat that the same as "insufficient evidence", not crash.
        """
        user_prompt = build_user_prompt(query, documents, failed_claims=failed_claims)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=MAX_TOKENS,
        )
        content = response.choices[0].message.content
        try:
            data = json.loads(content)
            return GeneratedAnswer(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None


def main():
    from app.agent.tools import build_default_registry
    from app.retrieval.documents import load_content_by_id

    registry = build_default_registry()
    generator = Generator()
    content_by_id = load_content_by_id()

    queries = ["What is T1059?", "How do I detect mimikatz?"]
    for query in queries:
        results = registry.call("search_knowledge_base", query=query, limit=3)["results"]
        evidence = [
            {"document_id": r["document_id"], "title": r["title"], "content": content_by_id[r["document_id"]]}
            for r in results
        ]

        answer = generator.generate(query, evidence)
        print(f"\nquery: {query!r}")
        if answer is None:
            print("  generation failed to parse")
            continue
        print(f"  insufficient_evidence={answer.insufficient_evidence}")
        for claim in answer.claims:
            print(f"  - {claim.text}  {claim.cited_document_ids}")


if __name__ == "__main__":
    main()
