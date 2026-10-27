import json
import urllib.request
import xml.etree.ElementTree as ET

# MERON - Controllo dei video recenti di Elisa True Crime
CHANNEL_ID = "UCxH0MkY6v0sjZzmMgW9TSRQ"

FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml?channel_id="
    + CHANNEL_ID
)

print("MERON - Controllo video ufficiali")

request = urllib.request.Request(
    FEED_URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(request, timeout=20) as response:
    xml_data = response.read()

root = ET.fromstring(xml_data)

ns = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015"
}

videos = []

for entry in root.findall("atom:entry", ns):
    title = entry.findtext("atom:title", default="", namespaces=ns)
    video_id = entry.findtext("yt:videoId", default="", namespaces=ns)

    if video_id:
        videos.append({
            "title": title,
            "url": "https://www.youtube.com/watch?v=" + video_id
        })

print(f"Video recenti trovati: {len(videos)}")

for video in videos:
    print(f"- {video['title']}")
    print(f"  {video['url']}")

# MERON - Salva i video per il confronto con Apple Podcasts
with open("video_recenti.json", "w", encoding="utf-8") as file:
    json.dump(
        {"videos": videos},
        file,
        ensure_ascii=False,
        indent=2
    )

print("MERON - File video_recenti.json creato correttamente!")
