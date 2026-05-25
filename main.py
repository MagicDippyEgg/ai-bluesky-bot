import os
import re
import sys
import random
from difflib import SequenceMatcher

from groq import Groq
from atproto import Client


MODEL = "llama-3.3-70b-versatile"
MAX_ATTEMPTS = 2
RECENT_LIMIT = 15
SIMILARITY_THRESHOLD = 0.58

POST_STYLES = [
    "a weird observation",
    "a tiny embarrassing confession",
    "a mildly existential thought",
    "an absurd overreaction",
    "a fake complaint about something trivial",
    "a strangely specific memory",
    "a dumb late-night thought",
    "an offbeat technology thought",
    "a random everyday annoyance",
    "something that sounds believable but oddly phrased",
    "a short joke with a dry punchline",
    "a thought that starts normal and gets weird",
]

SYSTEM_PROMPT = """
You write like a real person posting on Bluesky.
You are casual, natural, and slightly weird, but not repetitive.
Do not sound like a template.
Do not use hashtags.
Do not use quote marks.
Keep it under 250 characters.
Lowercase is preferred.
"""

def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def resolve_actor(client: Client, login_name: str) -> str:
    """
    Try to get the actual Bluesky handle or DID for recent-post lookup.
    Falls back to the login name if needed.
    """
    me = getattr(client, "me", None)
    if me is not None:
        handle = getattr(me, "handle", None)
        if isinstance(handle, str) and handle.strip():
            return handle.strip()

        did = getattr(me, "did", None)
        if isinstance(did, str) and did.strip():
            return did.strip()

    return login_name

def get_recent_posts(client: Client, actor: str, limit: int = RECENT_LIMIT) -> list[str]:
    """
    Best-effort fetch of recent posts from Bluesky.
    Tries a few common atproto client call styles.
    """
    candidates = [
        lambda: client.get_author_feed(actor=actor, limit=limit),
        lambda: client.get_author_feed({"actor": actor, "limit": limit}),
        lambda: client.app.bsky.feed.get_author_feed({"actor": actor, "limit": limit}),
        lambda: client.app.bsky.feed.get_author_feed(params={"actor": actor, "limit": limit}),
    ]

    last_error = None

    for fetch in candidates:
        try:
            result = fetch()

            feed = None
            if hasattr(result, "feed"):
                feed = result.feed
            elif isinstance(result, dict):
                feed = result.get("feed")

            if not feed:
                return []

            posts = []
            for item in feed:
                post = None
                if hasattr(item, "post"):
                    post = item.post
                elif isinstance(item, dict):
                    post = item.get("post")

                if post is None:
                    continue

                record = getattr(post, "record", None)
                if record is None and isinstance(post, dict):
                    record = post.get("record")

                text = None
                if record is not None:
                    text = getattr(record, "text", None)
                    if text is None and isinstance(record, dict):
                        text = record.get("text")

                if isinstance(text, str) and text.strip():
                    posts.append(text.strip())

            return posts

        except Exception as e:
            last_error = e

    print(f"Could not fetch recent posts: {last_error}")
    return []

def is_too_similar(candidate: str, recent_posts: list[str]) -> bool:
    candidate = candidate.strip()
    if not candidate:
        return True

    if len(candidate) > 250:
        return True

    for post in recent_posts:
        if similarity(candidate, post) >= SIMILARITY_THRESHOLD:
            return True

    return False

def build_prompt(style: str, recent_posts: list[str]) -> str:
    recent_block = "\n".join(f"- {post}" for post in recent_posts[:RECENT_LIMIT]) if recent_posts else "- none"

    return f"""
Generate ONE short Bluesky post.

This one should feel like: {style}

Rules:
- lowercase preferred
- no hashtags
- no quote marks
- no emoji spam
- under 250 characters
- weird, funny, relatable, or absurd
- sound like a real person posting random thoughts online
- avoid sounding like the recent posts below
- vary the structure naturally instead of copying a common pattern

Recent posts:
{recent_block}
""".strip()

def clean_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\n\r\"'")
    return text

def main():
    groq_api_key = os.environ.get("GROQ_API_KEY")
    bsky_username = os.environ.get("BSKY_USERNAME")
    bsky_password = os.environ.get("BSKY_PASSWORD")

    if not groq_api_key or not bsky_username or not bsky_password:
        print("Missing one or more environment variables: GROQ_API_KEY, BSKY_USERNAME, BSKY_PASSWORD")
        sys.exit(1)

    groq_client = Groq(api_key=groq_api_key)

    bsky = Client()
    bsky.login(bsky_username, bsky_password)

    actor = resolve_actor(bsky, bsky_username)
    recent_posts = get_recent_posts(bsky, actor, RECENT_LIMIT)

    print(f"Loaded {len(recent_posts)} recent posts.")

    post_text = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        style = random.choice(POST_STYLES)
        prompt = build_prompt(style, recent_posts)

        response = groq_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=1.35,
            max_tokens=80,
        )

        candidate = clean_output(response.choices[0].message.content)

        print(f"\nAttempt {attempt}:")
        print(candidate)

        if not is_too_similar(candidate, recent_posts):
            post_text = candidate[:250]
            break

    if post_text is None:
        print("\nNo post felt fresh enough. Not posting.")
        sys.exit(0)

    bsky.send_post(post_text)
    print("\nPosted successfully!")
    print(post_text)

if __name__ == "__main__":
    main()
    
