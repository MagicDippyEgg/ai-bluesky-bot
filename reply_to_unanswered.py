import os
import random
from datetime import datetime, timezone

from groq import Groq
from atproto import Client, models


LOOKBACK_POSTS = int(os.getenv("LOOKBACK_POSTS", "25"))
THREAD_DEPTH = int(os.getenv("THREAD_DEPTH", "100"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pick_text(obj) -> str:
    """
    Tries a few likely field layouts so the script is a bit more resilient
    across SDK versions.
    """
    if obj is None:
        return ""
    for attr_path in ("text", "record.text", "post.text", "value.text"):
        cur = obj
        ok = True
        for part in attr_path.split("."):
            if not hasattr(cur, part):
                ok = False
                break
            cur = getattr(cur, part)
        if ok and isinstance(cur, str):
            return cur
    return ""


def pick_uri(obj) -> str:
    if obj is None:
        return ""
    for attr in ("uri",):
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if isinstance(val, str):
                return val
    return ""


def pick_cid(obj) -> str:
    if obj is None:
        return ""
    for attr in ("cid",):
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if isinstance(val, str):
                return val
    return ""


def pick_handle(post) -> str:
    try:
        return post.author.handle
    except Exception:
        return ""


def is_real_post_node(node) -> bool:
    return hasattr(node, "post") and node.post is not None


def iter_descendants(node):
    """
    Yields every descendant ThreadViewPost under a thread node.
    """
    for child in getattr(node, "replies", []) or []:
        if is_real_post_node(child):
            yield child
            yield from iter_descendants(child)


def has_bot_reply_descendant(node, bot_handle: str) -> bool:
    for child in iter_descendants(node):
        if pick_handle(child.post).lower() == bot_handle.lower():
            return True
    return False


def get_root_and_candidates(thread, bot_handle: str):
    """
    Returns:
      root_post
      candidate_reply_nodes = replies that:
        - are not authored by the bot
        - do not already have a bot reply under them
    """
    root_post = thread.post
    candidates = []

    for child in getattr(thread, "replies", []) or []:
        if not is_real_post_node(child):
            continue

        author = pick_handle(child.post)
        if author.lower() == bot_handle.lower():
            continue

        if has_bot_reply_descendant(child, bot_handle):
            continue

        candidates.append(child)

    return root_post, candidates


def generate_reply(groq_client: Groq, root_text: str, target_text: str) -> str:
    prompt = f"""
You are writing a Bluesky reply.

Original post:
{root_text}

Reply you are responding to:
{target_text}

Rules:
- sound like a real person
- be aware of both the original post and the reply
- keep it under 220 characters
- lowercase preferred
- no hashtags
- no mention of being an ai
- do not be overly polished
- return only the reply text
""".strip()

    resp = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.1,
        max_tokens=80,
    )

    text = resp.choices[0].message.content.strip()
    text = " ".join(text.split())
    return text[:300]


def main():
    handle = os.environ["BSKY_USERNAME"]
    password = os.environ["BSKY_PASSWORD"]
    groq_key = os.environ["GROQ_API_KEY"]

    client = Client()
    client.login(handle, password)

    feed = client.get_author_feed(actor=handle, limit=LOOKBACK_POSTS)

    bot_handle = handle
    all_candidates = []
    candidate_meta = {}

    for item in getattr(feed, "feed", []) or []:
        if getattr(item, "reason", None) is not None:
            continue

        post = getattr(item, "post", None)
        if post is None:
            continue

        try:
            thread_res = client.get_post_thread(uri=pick_uri(post), depth=THREAD_DEPTH)
            thread = thread_res.thread
        except Exception as e:
            print(f"Skipping thread fetch for {pick_uri(post)}: {e}")
            continue

        root_post, candidates = get_root_and_candidates(thread, bot_handle)

        for node in candidates:
            reply_post = node.post
            all_candidates.append(node)
            candidate_meta[id(node)] = {
                "root_text": pick_text(root_post),
                "reply_text": pick_text(reply_post),
                "root_ref": models.create_strong_ref(root_post),
                "parent_ref": models.create_strong_ref(reply_post),
                "reply_uri": pick_uri(reply_post),
            }

    if not all_candidates:
        print("No unanswered replies found. Exiting cleanly.")
        return

    chosen = random.choice(all_candidates)
    meta = candidate_meta[id(chosen)]

    groq_client = Groq(api_key=groq_key)
    reply_text = generate_reply(
        groq_client,
        root_text=meta["root_text"],
        target_text=meta["reply_text"],
    )

    if not reply_text:
        print("Generated an empty reply. Exiting.")
        return

    print("Replying to:", meta["reply_uri"])
    print("Reply text:", reply_text)

    client.send_post(
        text=reply_text,
        reply_to=models.AppBskyFeedPost.ReplyRef(
            parent=meta["parent_ref"],
            root=meta["root_ref"],
        ),
    )

    print("Reply posted successfully.")


if __name__ == "__main__":
    main()