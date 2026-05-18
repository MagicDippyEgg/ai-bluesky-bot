import os
from groq import Groq
from atproto import Client

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

PROMPT = """
Write ONE short Bluesky bio/about line.

Rules:
- 120 characters max
- lowercase preferred
- funny, a little weird, but not cringe
- no hashtags
- no emoji spam
- no mention of being an ai bot
- should sound like a real person
- return only the bio text
"""

def make_bio() -> str:
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "user", "content": PROMPT}
        ],
        temperature=1.1,
        max_tokens=60,
    )

    bio = response.choices[0].message.content.strip()
    bio = bio.strip('"').strip("'")
    bio = " ".join(bio.split())
    return bio[:256]


def to_plain_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return dict(value)


def main():
    handle = os.environ["BSKY_USERNAME"]
    password = os.environ["BSKY_PASSWORD"]

    new_bio = make_bio()
    print("Generated bio:", new_bio)

    client = Client()
    client.login(handle, password)

    # Read the current profile record so we preserve everything else.
    current = client.com.atproto.repo.get_record({
        "repo": handle,
        "collection": "app.bsky.actor.profile",
        "rkey": "self",
    })

    current_profile = to_plain_dict(getattr(current, "value", None))

    # Preserve all existing fields, replace only the description.
    updated_profile = dict(current_profile)
    updated_profile["py_type"] = "app.bsky.actor.profile"
    updated_profile["description"] = new_bio

    # Keep a display name if the account is new or empty.
    if not updated_profile.get("display_name"):
        updated_profile["display_name"] = handle.split(".")[0]

    # Remove None values so we do not accidentally send junk.
    updated_profile = {k: v for k, v in updated_profile.items() if v is not None}

    payload = {
        "repo": handle,
        "collection": "app.bsky.actor.profile",
        "rkey": "self",
        "record": updated_profile,
    }

    # Compare-and-swap for safety if the SDK returned a CID.
    current_cid = getattr(current, "cid", None)
    if current_cid:
        payload["swap_record"] = current_cid

    client.com.atproto.repo.put_record(payload)
    print("Bio updated successfully.")


if __name__ == "__main__":
    main()