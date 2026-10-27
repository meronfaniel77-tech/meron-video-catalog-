
import json
from pathlib import Path
from collections import Counter

CONTROLLO = Path("controllo_video_meron.json")
CATALOGO = Path("videos.json")


def leggi_json(percorso):
    with percorso.open("r", encoding="utf-8") as file:
        return json.load(file)


def salva_json(percorso, dati):
    with percorso.open("w", encoding="utf-8") as file:
        json.dump(dati, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main():
    controllo = leggi_json(CONTROLLO)
    catalogo = leggi_json(CATALOGO)

    if not isinstance(controllo.get("results"), list):
        raise ValueError("Formato controllo non valido")

    videos = catalogo.get("videos")

    if not isinstance(videos, dict):
        raise ValueError("Formato videos.json non valido")

    candidati = []

    for episodio in controllo["results"]:
        if episodio.get("status") != "CANDIDATO_FORTE":
            continue

        opzioni = episodio.get("candidates", [])

        if not opzioni:
            continue

        migliore = opzioni[0]
        url = migliore.get("url", "")

        if not url.startswith("https://www.youtube.com/watch?v="):
            continue

        candidati.append({
            "id": str(episodio["trackId"]),
            "episode": episodio["episode"],
            "url": url,
            "score": migliore.get("score", 0)
        })

    conteggi = Counter(c["url"] for c in candidati)

    url_esistenti = {
        video.get("youtubeUrl")
        for video in videos.values()
        if isinstance(video, dict)
    }

    aggiunti = 0
    esclusi = 0

    for candidato in candidati:
        episodio_id = candidato["id"]
        url = candidato["url"]

        if episodio_id in videos:
            esclusi += 1
            continue

        if conteggi[url] > 1:
            esclusi += 1
            continue

        if url in url_esistenti:
            esclusi += 1
            continue

        videos[episodio_id] = {
            "podcast": "Elisa True Crime",
            "episode": candidato["episode"],
            "youtubeUrl": url,
            "verified": False
        }

        url_esistenti.add(url)
        aggiunti += 1

    salva_json(CATALOGO, catalogo)

    print("MERON - AGGIORNAMENTO CATALOGO")
    print("Candidati forti:", len(candidati))
    print("Nuovi collegamenti aggiunti:", aggiunti)
    print("Collegamenti esclusi:", esclusi)
    print("Totale catalogo:", len(videos))


if __name__ == "__main__":
    main()
