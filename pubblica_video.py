
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
        json.dump(
            dati,
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")


def main():
    controllo = leggi_json(CONTROLLO)
    catalogo = leggi_json(CATALOGO)

    risultati = controllo.get("results")

    if not isinstance(risultati, list):
        raise ValueError(
            "Formato controllo non valido"
        )

    videos = catalogo.get("videos")

    if not isinstance(videos, dict):
        raise ValueError(
            "Formato videos.json non valido"
        )

    candidati_forti = 0
    candidati_approvati = []

    for episodio in risultati:
        if episodio.get("status") != "CANDIDATO_FORTE":
            continue

        candidati_forti += 1

        opzioni = episodio.get("candidates", [])

        if not opzioni:
            continue

        migliore = opzioni[0]
        url = migliore.get("url", "")

        if not isinstance(url, str):
            continue

        if not url.startswith(
            "https://www.youtube.com/watch?v="
        ):
            continue

        # Solo le approvazioni esplicite
        # consentono la pubblicazione.
        # Il punteggio automatico non basta.
        if episodio.get("approved") is not True:
            continue

        candidati_approvati.append({
            "id": str(episodio["trackId"]),
            "episode": episodio["episode"],
            "url": url,
        })

    conteggi = Counter(
        candidato["url"]
        for candidato in candidati_approvati
    )

    url_esistenti = {
        video.get("youtubeUrl")
        for video in videos.values()
        if isinstance(video, dict)
    }

    aggiunti = 0
    esclusi = 0

    for candidato in candidati_approvati:
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
            "verified": True
        }

        url_esistenti.add(url)
        aggiunti += 1

    if aggiunti > 0:
        salva_json(CATALOGO, catalogo)

    print("MERON - AGGIORNAMENTO SICURO")
    print(
        "Candidati forti:",
        candidati_forti
    )
    print(
        "Candidati approvati:",
        len(candidati_approvati)
    )
    print(
        "Nuovi collegamenti aggiunti:",
        aggiunti
    )
    print(
        "Collegamenti esclusi:",
        esclusi
    )
    print(
        "Totale catalogo:",
        len(videos)
    )


if __name__ == "__main__":
    main()
