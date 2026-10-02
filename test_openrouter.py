import os
from dotenv import load_dotenv
load_dotenv()
import httpx

api_key = os.environ["OPENROUTER_API_KEY"]
model = "deepseek/deepseek-v3.2"

prompt_test = (
    "You are a short-story writer for text-to-speech (TTS) narration.\n"
    "Write in English only.\n"
    "- Subject of the story: write in the style of short erotica captions commonly used "
    "for adult short-form video content. INVENT an original scenario with specific "
    "characters and a clear premise - do not just describe or caption what is shown.\n"
    "- CRITICAL sentence style: use very short, fragmented, punchy sentences, often "
    "WITHOUT a full subject or verb, like a string of quick beats rather than flowing "
    "prose. Example of the target rhythm: \"No panties. No warnings. Just her ass in the "
    "air.\" or \"The bedroom was suicide. The hallway was worse.\" Most sentences should be "
    "under 8 words. Avoid long connected sentences with multiple clauses.\n"
    "- Weave in one short line of dialogue in quotes for impact, not a full conversation.\n"
    "- Include explicit sensory and physical detail, but only details that build the "
    "fantasy and narrative - never a literal description of what is visually shown.\n"
    "- Start in medias res, no slow scene-setting.\n"
    "- End on a sharp, punchy final line, ideally with a twist, irony, or a reveal.\n"
    "- Output format: a hook of 15-25 words, then --- on its own line, then a 180-220 word "
    "story body.\n"
)

resp = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"model": model, "messages": [{"role": "user", "content": prompt_test}], "max_tokens": 1000},
    timeout=60,
)
print("Statut:", resp.status_code)
data = resp.json()
if "choices" in data:
    print(data["choices"][0]["message"].get("content", "(vide)"))
else:
    print("Erreur:", data)