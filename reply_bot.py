import os
import random

from groq import Groq
from atproto import Client, models

model = "llama-3.3-70b-versatile"

DEFAULT_QUERIES = [
    "random thoughts",
    "retro tech",
    "windows 7",
    "old computers",
    "minecraft",
    "half life",
    "portal",
    "bluesky",
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


def get_value(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def clean_text(text: str) -> str:
    text = " ".join(text.strip().split())
    return text.strip('"').strip("'")


def pick_queries():
    raw = os.getenv("SEARCH_QUERIES", "").strip()
    if raw:
        queries = [q.strip() for q in raw.split(",") if q.strip()]
    else:
        queries = DEFAULT_QUERIES[:]
    random.shuffle(queries)
    return queries


def search_posts(client: Client, query: str):
    params = models.AppBskyFeedSearchPosts.Params(
        q=query,
        limit=25,
        sort="latest",
    )
    response = client.app.bsky.feed.search_posts(params)
    return response.posts


def choose_candidate(posts, my_handle: str):
    my_handle = my_handle.lower().strip()
    candidates = []

    for post in posts:
        author = (get_value(get_value(post, "author"), "handle", "") or "").lower().strip()
        text = (get_value(get_value(post, "record"), "text", "") or "").strip()

        if not text:
            continue
        if author == my_handle:
            continue

        candidates.append(post)

    if not candidates:
        return None

    return random.choice(candidates)


def make_reply(query: str, post) -> str:
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    author = get_value(get_value(post, "author"), "handle", "unknown")
    text = get_value(get_value(post, "record"), "text", "")

    prompt = PROMPT_TEMPLATE.format(
        query=query,
        author=author,
        text=text,
    )

    response = groq_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
        max_tokens=80,
    )

    reply = response.choices[0].message.content.strip()
    reply = clean_text(reply)
    return reply[:240]


def build_reply_ref(post):
    parent_ref = models.create_strong_ref(post)

    record = get_value(post, "record")
    reply_info = get_value(record, "reply")

    root_obj = get_value(reply_info, "root")
    if root_obj:
        root_ref = models.create_strong_ref(root_obj)
    else:
        root_ref = parent_ref

    return models.AppBskyFeedPost.ReplyRef(
        root=root_ref,
        parent=parent_ref,
    )


def main():
    handle = os.environ["BSKY_USERNAME"]
    password = os.environ["BSKY_PASSWORD"]

    client = Client()
    client.login(handle, password)

    queries = pick_queries()
    target = None
    used_query = None

    for query in queries:
        print("Search query:", query)
        posts = search_posts(client, query)
        target = choose_candidate(posts, handle)

        if target:
            used_query = query
            break

    if not target:
        print("No suitable post found.")
        return

    target_author = get_value(get_value(target, "author"), "handle", "unknown")
    target_text = get_value(get_value(target, "record"), "text", "")

    print(f"Target: @{target_author}")
    print(f"Text: {target_text}")

    reply_text = make_reply(used_query or "random thoughts", target)
    print("Reply text:", reply_text)

    reply_to = build_reply_ref(target)

    client.send_post(
        text=reply_text,
        reply_to=reply_to,
    )

    print("Reply posted successfully.")


if __name__ == "__main__":
    main()
