
import json
import subprocess
import sys

# MERON - Recupera l'archivio pubblico dei video YouTube
# Canale ufficiale Elisa True Crime
CHANNEL_ID = "UCxH0MkY6v0sjZzmMgW9TSRQ"

CHANNEL_URL = (
    f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"
)

OUTPUT_FILE = "archivio_youtube.json"


def recupera_archivio():
    print("MERON - Recupero archivio YouTube")
    print(f"Canale: {CHANNEL_URL}")

    comando = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--ignore-errors",
        "--no-warnings",
        CHANNEL_URL
    ]

    risultato = subprocess.run(
        comando,
        capture_output=True,
        text=True,
        timeout=180
    )

    if risultato.returncode != 0:
        print("MERON - Recupero archivio non riuscito")
        print(risultato.stderr[-2000:])
        sys.exit(1)

    try:
        dati = json.loads(risultato.stdout)
    except json.JSONDecodeError:
        print("MERON - YouTube non ha restituito dati JSON validi")
        sys.exit(1)

    videos = []

    for entry in dati.get("entries", []):
        if not entry:
            continue

        video_id = entry.get("id")
        titolo = entry.get("title", "")

        if not video_id or not titolo:
            continue

        videos.append({
            "title": titolo,
            "url": f"https://www.youtube.com/watch?v={video_id}"
        })

    print(f"MERON - Video storici recuperati: {len(videos)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            {"videos": videos},
            file,
            ensure_ascii=False,
            indent=2
        )

    print(f"MERON - Archivio salvato in {OUTPUT_FILE}")

    for video in videos[:10]:
        print(f"- {video['title']}")
        print(f"  {video['url']}")


if __name__ == "__main__":
    recupera_archivio()
