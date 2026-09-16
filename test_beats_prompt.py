import os 
from groq import Groq 
from dotenv import load_dotenv 
load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])


prompt = """You are converting a news story into structured "beats" for a motion-graphics video. Each beat should be classified by type and given the data needed to render it.

SOURCE MATERIAL:
Title: US pushes countries to pick a side in the AI race, China pushes back
Article body: The rivalry between the United States and China in artificial intelligence is taking on a new dimension. Washington is considering asking dozens of countries to choose between the American and Chinese technology ecosystems. Some partners could be warned that cooperating with Chinese AI initiatives could jeopardize their participation in a US-backed technology coalition. Beijing opposes this approach, calling for respect for each country's digital sovereignty and arguing countries should be free to choose their tech partners. The global AI race is no longer just a competition between models and companies, it is increasingly a geopolitical one. Europe has real strengths in this fight: the European Union represents around 6 percent of the world's population but accounts for 15 percent of its researchers and produces nearly one fifth of the world's most highly cited scientific publications. Christine Lagarde says one of the main problems is Europe's difficulty turning scientific excellence into commercial success, partly because its markets and financing remain too fragmented. Still, there are signs of movement: euro area companies plan to allocate an average of around 9 percent of their total investment to AI in 2026.

For EACH beat (roughly one per sentence or key idea), output an object with:
- "type": one of "chart_counter", "chart_comparison", "chart_line", "icon_text", "key_statement", "timeline", "process_flow", "versus", "map_location", "quote_card", "progress_meter", "before_after"
- "text": the narration text for this beat (short, punchy, matching the beat)
- Fields required per type:
  - chart_counter: "value" (plain integer, never pre-abbreviated), "label" (string)
  - chart_comparison: "items" (array of {"label": string, "value": number})
  - chart_line: "points" (array of {"label": string, "value": number}, 3-6 points showing a trend over time)
  - icon_text: "icon" (a generic concept keyword, e.g. "warning", "money", "chip" — never a brand name)
  - key_statement: "emphasisWords" (array of 1-2 key words) — DEFAULT fallback for narrative/opinion beats with no clear data
  - timeline: "events" (array of {"marker": string, "label": string}, 2-5 events)
  - process_flow: "steps" (array of 2-4 short step strings)
  - versus: "left" and "right" (each {"label": string, "value": string})
  - map_location: "locationName", "latitude", "longitude" — only if a specific real place is mentioned
  - quote_card: "quote", "attribution" — only if the source contains an actual quoted/attributed statement
  - progress_meter: "value", "maxValue", "label" — only for percentage/completion-style data
  - before_after: "beforeLabel", "afterLabel" — only for clear contrast/change framing

Always use the full raw integer for any numeric "value" field (e.g. 70000000000, not 70) — never pre-abbreviate numbers into the label.

The anti-fabrication rule applies to inventing details not in the source — it 
does NOT mean avoiding specific types cautiously. If the source contains an 
actual quoted or clearly attributed statement (e.g. "Christine Lagarde says..."), 
use quote_card confidently, since this is real source content, not an invention.

CRITICAL: Never invent dates, numbers, locations, or facts not present in the 
source material. If a beat doesn't fit a specific type using only real 
information from the source, use key_statement instead. This applies 
especially to "timeline" (do not invent dates) and "map_location" (do not 
invent coordinates) — only use these types when the source explicitly 
provides real chronological events with actual dates, or a real named 
location, respectively.

Vary the types used across beats — don't overuse one type. Prefer the most 
specific fitting type when the content genuinely supports it, but don't force 
map_location, quote_card, progress_meter, or before_after if the story 
doesn't naturally contain that kind of content.

Output ONLY valid JSON, no markdown fences, no explanation, in this shape:
{"beats": [ {...}, {...}, ... ]}
"""

response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[{"role": "user", "content": prompt}]
)
print(response.choices[0].message.content)
