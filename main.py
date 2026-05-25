import os
from groq import Groq
from atproto import Client

# ===== CONFIG =====

PROMPT = """
You are a mildly sleep deprived Gen Z internet user.

Generate ONE short Bluesky post.

Rules:
- lowercase preferred
- no hashtags
- no quotes
- no emojis spam
- under 250 characters
- weird, funny, relatable, or absurd
- sound like a real person posting random thoughts online
"""

# ===== GROQ =====

groq_client = Groq(
    api_key=os.environ["GROQ_API_KEY"]
)

response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {
            "role": "user",
            "content": PROMPT
        }
    ],
    temperature=1.2,
    max_tokens=60
)

post_text = response.choices[0].message.content.strip()

# Safety trim
post_text = post_text[:300]

print("Generated post:")
print(post_text)

# ===== BLUESKY =====

bsky = Client()

bsky.login(
    os.environ["BSKY_USERNAME"],
    os.environ["BSKY_PASSWORD"]
)

bsky.send_post(post_text)

print("Posted successfully!")
