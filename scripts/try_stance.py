"""Exercise the real stance extractor + deterministic comparison on sample plan pairs.

    python -m scripts.try_stance

Prints each plan's stance and, for each pair, the comparison result. Use it to tune
the extraction prompt and the normalisation rules against real model output.
"""
from __future__ import annotations

import asyncio
import json
import time

from app.config import get_settings
from app.core.clash import compare
from app.core.embeddings import cosine
from app.core.providers import get_providers

PAIRS = [
    (
        "golden: session model vs login endpoint (should be HARD)",
        "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens.",
        "Add a POST /login endpoint that creates a server-side session and returns the session id.",
    ),
    (
        "same subsystem, compatible positions (should be SOFT at most)",
        "Add a logout endpoint that deletes the server-side session row and clears the cookie.",
        "Add rate limiting to the login endpoint: 5 attempts per minute per IP, respond 429 after that.",
    ),
    (
        "different files, same contract disagreement (should be HARD)",
        "Change the users API so that GET /users/{id} returns 404 with an empty body when the user does not exist.",
        "Build the admin dashboard user page; it calls GET /users/{id} and expects a 200 with {user: null} for missing users.",
    ),
    (
        "unrelated (should be CLEAR)",
        "Add a CSV export button to the reports page that downloads the current table.",
        "Migrate the image upload handler from local disk to S3 with presigned URLs.",
    ),
    (
        "same concept, wording differs only (should NOT be hard)",
        "Store password reset tokens in Redis with a 15 minute TTL.",
        "Password-reset tokens go into redis and expire after fifteen minutes.",
    ),
]


async def main() -> None:
    settings = get_settings()
    providers = get_providers()
    print(f"stance provider: {type(providers.stance).__name__}  model: {settings.stance_model}")
    print(f"embedding provider: {type(providers.embeddings).__name__}\n")

    for title, a_text, b_text in PAIRS:
        print("=" * 100)
        print(title)
        t = time.perf_counter()
        a, b = await asyncio.gather(providers.stance.extract(a_text), providers.stance.extract(b_text))
        ea, eb = await asyncio.gather(providers.embeddings.embed(a_text), providers.embeddings.embed(b_text))
        ms = int((time.perf_counter() - t) * 1000)
        for label, text, st in (("A", a_text, a), ("B", b_text, b)):
            print(f"\n{label}: {text}")
            d = st.to_dict()
            d.pop("summary", None)
            print("   " + json.dumps(d))
        sim = cosine(ea, eb)
        cmp = compare(b, a, sim)
        print(f"\n-> similarity={sim:.3f}  overlap={cmp.concept_overlap}  shared={cmp.shared_concepts}")
        for div in cmp.divergent_axes:
            print(f"   divergent {div.axis}: B={div.ours!r} vs A={div.theirs!r}")
        print(f"   SEVERITY: {cmp.severity.upper()}   ({ms} ms for both extractions)\n")


if __name__ == "__main__":
    asyncio.run(main())
