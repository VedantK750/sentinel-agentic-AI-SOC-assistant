import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from .prompts import SYSTEM_PROMPT, build_user_prompt

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT / ".env")

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-flash")

# The endpoint is a reasoning model that writes hidden "reasoning_content" tokens
# before the visible answer, billed against the same completion budget -- a request
# capped at a few hundred tokens can exhaust itself on reasoning and return truncated
# JSON (finish_reason="length") with empty/partial `content`. How much reasoning it
# does is query-dependent, not a fixed overhead: a harder or more sensitive-sounding
# query (verified case: "How to do WIFI hacking on windows?", which visibly made the
# model deliberate at length about how to frame the answer) can exhaust even a budget
# that was previously plenty for simpler queries. A fixed constant is therefore not
# actually robust -- retrying with an expanding budget on truncation is, since it
# reacts to what this specific request needed instead of guessing a ceiling upfront.
# See DECISIONS.md.
INITIAL_MAX_TOKENS = 2048
MAX_TOKENS_RETRIES = 2  # 2048 -> 4096 -> 8192

# Found the hard way: a query that makes the model reason unusually long can leave a
# single HTTP call to this endpoint hanging for minutes with no error and no visible
# progress -- confirmed by watching a real request sit at 70%+ CPU for 3.5 minutes
# before the endpoint itself returned a 500. Without a client-side timeout, a single
# slow or wedged call blocks the whole pipeline indefinitely with nothing to show for
# it. 90s is generous relative to every successful call observed so far, but bounded.
REQUEST_TIMEOUT = 90.0


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

    def __init__(self, model=DEFAULT_MODEL, timeout=REQUEST_TIMEOUT):
        self.client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ["LLM_ENDPOINT"],
            timeout=timeout,
        )
        self.model = model

    def generate(self, query, documents, failed_claims=None) -> Optional[GeneratedAnswer]:
        """Returns None if the call fails outright (timeout, network, endpoint error)
        or the response isn't valid JSON matching the schema even after expanding the
        token budget -- callers should treat all of these as "insufficient evidence",
        not crash. GenerationPipeline's own regen-or-reject retry is what gets a
        second attempt; this method doesn't retry API errors itself since the SDK
        client already retries transient ones internally before ever raising here.
        """
        user_prompt = build_user_prompt(query, documents, failed_claims=failed_claims)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        max_tokens = INITIAL_MAX_TOKENS
        for attempt in range(MAX_TOKENS_RETRIES + 1):
            print(f"  [generator] calling LLM (max_tokens={max_tokens})...")
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    max_tokens=max_tokens,
                )
            except OpenAIError as e:
                print(f"  [generator] LLM call failed ({e!r}); treating as insufficient evidence")
                return None

            choice = response.choices[0]
            if choice.finish_reason == "length" and attempt < MAX_TOKENS_RETRIES:
                max_tokens *= 2
                continue
            try:
                return GeneratedAnswer(**json.loads(choice.message.content))
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
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
