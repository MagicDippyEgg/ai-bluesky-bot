import os
import random
from datetime import datetime, timezone

import requests
from groq import Groq
from atproto import Client, models

PUBLIC_BSKY_API = "https://public.api.bsky.app"

DEFAULT_QUERIES = [
    "retro tech",
    "windows 7",
    "old computers",
    "minecraft",
    "bluesky",
    "half life",
    "portal",
    "random thoughts",
]

PROMPT_TEMPLATE = """
Write a short, casual reply to this Bluesky post.

Rules:
- sound natural and human
- lowercase preferred
- no hashtags
- no links
- no emoji spam
- do not mention being an ai
- do not be rude
- keep it under 180 characters
- return only the reply text

Search topic: {query}
Post author: @{author}
Post text: {text}
"""

def clean_text(text: str) -> str:
    text = " ".join(text.strip().split())
    text = text.strip('"').strip("'")
    return text

def pick_query() -> str:
    raw = os.getenv("SEARCH_QUERIES", "").strip()
    if raw:
        queries = [q.strip() for q in raw.split(",") if q.strip()]
    else:
        queries = DEFAULT_QUERIES
    return random.choice(queries)

def search_posts(query: str) -> list[dict]:
    resp = requests.get(
        f"{PUBLIC_BSKY_API}/xrpc/app.bsky.feed.searchPosts",
        params={"q": query, "limit": 25},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("posts", [])

def choose_candidate(posts: list[dict], my_handle: str) -> dict | None:
    candidates = []
    my_handle = my_handle.lower().strip()

    for post in posts:
        author = (post.get("author") or {}).get("handle", "").lower().strip()
        text = ((post.get("record") or {}).get("text") or "").strip()

        if not text:
            continue
        if author == my_handle:
            continue

        candidates.append(post)

    if not candidates:
        return None

    return random.choice(candidates)

def make_reply(query: str, post: dict) -> str:
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    author = ((post.get("author") or {}).get("handle")) or "unknown"
    text = ((post.get("record") or {}).get("text")) or ""

    prompt = PROMPT_TEMPLATE.format(
        query=query,
        author=author,
        text=text,
    )

    response = groq_client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
        max_tokens=80,
    )

    reply = response.choices[0].message.content.strip()
    reply = clean_text(reply)
    return reply[:240]

def build_reply_ref(post: dict):
    parent_ref = models.create_strong_ref(
        type("Tmp", (), {"uri": post["uri"], "cid": post["cid"]})()
    )

    record = post.get("record") or {}
    reply_info = record.get("reply")

    if reply_info and reply_info.get("root") and reply_info.get("parent"):
        root_data = reply_info["root"]
        root_ref = models.create_strong_ref(
            type("Tmp", (), {"uri": root_data["uri"], "cid": root_data["cid"]})()
        )
    else:
        root_ref = parent_ref

    return models.AppBskyFeedPost.ReplyRef(parent=parent_ref, root=root_ref)

def main():
    handle = os.environ["BSKY_USERNAME"]
    password = os.environ["BSKY_PASSWORD"]

    query = pick_query()
    print("Search query:", query)

    posts = search_posts(query)
    if not posts:
        print("No posts found.")
        return

    target = choose_candidate(posts, handle)
    if not target:
        print("No suitable post found after filtering.")
        return

    target_author = ((target.get("author") or {}).get("handle")) or "unknown"
    target_text = ((target.get("record") or {}).get("text")) or ""
    print(f"Target: @{target_author}")
    print(f"Text: {target_text}")

    reply_text = make_reply(query, target)
    print("Reply text:", reply_text)

    client = Client()
    client.login(handle, password)

    reply_to = build_reply_ref(target)

    client.send_post(
        text=reply_text,
        reply_to=reply_to,
    )

    print("Reply posted successfully.")

if __name__ == "__main__":
    main()
