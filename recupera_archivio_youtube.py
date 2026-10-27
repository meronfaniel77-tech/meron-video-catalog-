
import json
import subprocess
import sys

# MERON - Archivio video Elisa True Crime
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
        print(
            "MERON - YouTube non ha restituito "
            "dati JSON validi"
        )
        sys.exit(1)

    videos = []
    descrizioni_trovate = 0
    ids_visti = set()

    for entry in dati.get("entries", []):
        if not entry:
            continue

        video_id = entry.get("id")
        titolo = entry.get("title", "")

        if not video_id or not titolo:
            continue

        if video_id in ids_visti:
            continue

        ids_visti.add(video_id)

        descrizione = entry.get("description") or ""

        if not isinstance(descrizione, str):
            descrizione = ""

        if descrizione.strip():
            descrizioni_trovate += 1

        videos.append({
            "id": video_id,
            "title": titolo,
            "description": descrizione[:5000],
            "url": (
                "https://www.youtube.com/watch?v="
                + video_id
            )
        })

    if not videos:
        print("ERRORE: nessun video recuperato")
        sys.exit(1)

    print(
        "MERON - Video storici recuperati:",
        len(videos)
    )

    print(
        "MERON - Descrizioni disponibili:",
        descrizioni_trovate
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            {"videos": videos},
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")

    print(
        "MERON - Archivio salvato in",
        OUTPUT_FILE
    )

    for video in videos[:5]:
        print("- " + video["title"])
        print("  " + video["url"])


if __name__ == "__main__":
    recupera_archivio()
