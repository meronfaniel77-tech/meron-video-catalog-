
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# MERON - RICONOSCIMENTO BILINGUE ITALIANO / INGLESE

FILE_APPLE = Path("episodi_apple.json")
FILE_YOUTUBE = Path("archivio_youtube.json")
FILE_CATALOGO = Path("videos.json")
FILE_RISULTATI = Path("controllo_video_meron.json")

MODELLO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

PAROLE_GENERALI = {
    "the", "and", "with", "from", "what", "when",
    "where", "who", "why", "how", "case", "story",
    "true", "crime", "elisa", "part", "episode",
    "this", "that", "into", "after", "before",
    "about", "their", "there", "were", "they",
    "have", "been", "will", "would", "could",
    "il", "lo", "la", "gli", "le", "un", "una",
    "uno", "di", "del", "della", "dei", "delle",
    "da", "dal", "dallo", "dalla", "dai",
    "in", "con", "per", "che", "cosa", "caso",
    "storia", "ep", "pt", "parte", "dopo",
    "sono", "era", "alla", "sua", "suo",
    "fatto", "fine", "hanno", "quella",
    "notte", "successo", "verita", "morte",
    "giorni", "nuova", "questa", "questo",
    "quello", "dove", "come", "quando",
    "perche", "anche", "tutti", "tutte",
    "essere", "stato", "stata", "dentro",
    "fuori", "ancora", "nella", "nelle",
    "nello", "negli", "sulla", "sulle",
    "sullo", "agli", "alle", "dalle",
    "dello", "dell", "dall"
}

PAROLE_TEMATICHE = {
    "omicidio", "assassino", "ucciso",
    "morto", "scomparso", "scomparsa",
    "madre", "padre", "figlia", "figlio",
    "famiglia", "marito", "moglie",
    "bambino", "bambini", "scuola",
    "prigione", "agghiacciante",
    "segreto", "lotteria", "matrimonio",
    "anni", "giorni", "delitto",
    "vittima", "polizia", "indagine",
    "criminale", "orrore", "mistero",
    "mostro", "killer", "murder",
    "death", "missing", "family",
    "mother", "father", "daughter",
    "son", "horror", "monster",
    "disappearance", "nightmare",
    "mystery", "crime", "victim"
}

# Correzioni di caratteri usati nei titoli YouTube.
CORREZIONI = {
    "mass4cro": "massacro",
    "mass4cre": "massacre",
    "k!ller": "killer",
    "k1ller": "killer",
    "mister0": "mistero",
    "incub0": "incubo",
    "0rr0re": "orrore",
    "sсhabusiness": "schabusiness"
}


def normalizza(testo):
    testo = str(testo or "").lower()

    testo = testo.replace("Ǝ", "e").replace("ǝ", "e")
    testo = testo.replace("∀", "a")
    testo = testo.replace("я", "r")
    testo = testo.replace("с", "c")

    for originale, corretto in CORREZIONI.items():
        testo = testo.replace(originale, corretto)

    testo = unicodedata.normalize("NFKD", testo)

    testo = "".join(
        carattere
        for carattere in testo
        if not unicodedata.combining(carattere)
    )

    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def pulisci_titolo(titolo):
    testo = str(titolo or "")
    testo = re.sub(
        r"^\s*ep\s*\.{0,2}\s*\d+\s*[:.\-]?\s*",
        "",
        testo,
        flags=re.IGNORECASE
    )
    return testo.strip()


def parole(testo):
    return {
        p for p in normalizza(testo).split()
        if len(p) >= 4
        and p not in PAROLE_GENERALI
        and not p.isdigit()
    }


def numero_parte(titolo):
    testo = normalizza(titolo)
    match = re.search(
        r"\b(?:pt|part|parte)\s*([1-9])\b",
        testo
    )
    return int(match.group(1)) if match else None


def leggi_json(percorso):
    with percorso.open("r", encoding="utf-8") as file:
        return json.load(file)


def analizza_nomi(titolo, titolo_video, frequenze):
    parole_apple = parole(titolo)
    parole_youtube = parole(titolo_video)

    comuni = parole_apple & parole_youtube

    # Termini rari e condivisi: indizio utile
    # di un nome proprio o un luogo specifico.
    rare = {
        p for p in comuni
        if p not in PAROLE_TEMATICHE
        and frequenze.get(p, 0) <= 3
    }

    return {
        "common": sorted(comuni),
        "title_matches": len(comuni),
        "rare_matches": len(rare),
        "rare_words": sorted(rare)
    }


def controlla():
    dati_apple = leggi_json(FILE_APPLE)
    dati_youtube = leggi_json(FILE_YOUTUBE)
    dati_catalogo = leggi_json(FILE_CATALOGO)

    episodi = dati_apple.get("episodes", [])
    video = dati_youtube.get("videos", [])
    catalogo = dati_catalogo.get("videos", {})

    if not isinstance(episodi, list):
        raise ValueError("Archivio Apple non valido")

    if not isinstance(video, list):
        raise ValueError("Archivio YouTube non valido")

    if not isinstance(catalogo, dict):
        raise ValueError("Catalogo MerON non valido")

    video_validi = [
        v for v in video
        if isinstance(v, dict)
        and isinstance(v.get("url"), str)
        and v["url"].startswith(
            "https://www.youtube.com/watch?v="
        )
        and v.get("title")
    ]

    if not video_validi:
        raise ValueError("Nessun video YouTube valido")

    print("MERON - RICONOSCIMENTO BILINGUE")
    print("Caricamento modello multilingue...")

    modello = SentenceTransformer(MODELLO)

    titoli_apple = [
        pulisci_titolo(e.get("titolo", ""))
        for e in episodi
    ]

    titoli_youtube = [
        str(v["title"])
        for v in video_validi
    ]

    print("Analisi dei titoli Apple...")
    vettori_apple = modello.encode(
        titoli_apple,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True
    )

    print("Analisi dei titoli YouTube...")
    vettori_youtube = modello.encode(
        titoli_youtube,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True
    )

    similarita = cosine_similarity(
        vettori_apple,
        vettori_youtube
    )

    frequenze = Counter()

    for titolo in titoli_youtube:
        frequenze.update(parole(titolo))

    risultati = []

    for indice, episodio in enumerate(episodi):
        titolo = episodio.get("titolo", "")
        candidati = []

        parte_apple = numero_parte(titolo)

        for j, elemento in enumerate(video_validi):
            titolo_video = elemento["title"]
            parte_video = numero_parte(titolo_video)

            if (
                parte_apple is not None
                and parte_video is not None
                and parte_apple != parte_video
            ):
                continue

            somiglianza = float(
                similarita[indice][j]
            )

            analisi = analizza_nomi(
                titolo,
                titolo_video,
                frequenze
            )

            # Il modello comprende entrambe le lingue.
            # I termini rari aggiungono conferma.
            punteggio = (
                somiglianza * 10
                + min(analisi["rare_matches"], 3) * 1.5
            )

            parte_incerta = (
                (parte_apple is None)
                != (parte_video is None)
            )

            candidati.append({
                "title": titolo_video,
                "url": elemento["url"],
                "score": round(punteggio, 3),
                "similarity": round(somiglianza, 4),
                "common": analisi["common"],
                "title_matches": analisi["title_matches"],
                "rare_matches": analisi["rare_matches"],
                "rare_words": analisi["rare_words"],
                "parte_incerta": parte_incerta
            })

        candidati.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        migliori = candidati[:3]
        stato = "DA_VERIFICARE"

        if migliori:
            primo = migliori[0]

            secondo = (
                migliori[1]["score"]
                if len(migliori) > 1
                else 0
            )

            # Soglie conservative:
            # il risultato e' un candidato,
            # non una verifica definitiva.
            if (
                primo["similarity"] >= 0.78
                and primo["score"] >= 8.0
                and not primo["parte_incerta"]
                and (
                    primo["rare_matches"] >= 1
                    or primo["similarity"] >= 0.90
                )
                and (
                    secondo == 0
                    or primo["score"] >= secondo + 1.5
                )
            ):
                stato = "CANDIDATO_FORTE"

        risultati.append({
            "trackId": episodio.get("id"),
            "episode": titolo,
            "status": stato,
            "candidates": migliori
        })

    # Evita che due episodi forti puntino
    # automaticamente allo stesso video.
    utilizzi = defaultdict(list)

    for risultato in risultati:
        if (
            risultato["status"] == "CANDIDATO_FORTE"
            and risultato["candidates"]
        ):
            url = risultato["candidates"][0]["url"]
            utilizzi[url].append(risultato)

    for associati in utilizzi.values():
        if len(associati) > 1:
            for risultato in associati:
                risultato["status"] = "DA_VERIFICARE"

    forti = sum(
        r["status"] == "CANDIDATO_FORTE"
        for r in risultati
    )

    gia_collegati = sum(
        str(r["trackId"]) in catalogo
        for r in risultati
    )

    print("Episodi Apple:", len(episodi))
    print("Video YouTube:", len(video_validi))
    print("Candidati forti:", forti)
    print("Da verificare:", len(risultati) - forti)
    print("Episodi gia' nel catalogo:", gia_collegati)

    with FILE_RISULTATI.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            {"results": risultati},
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")

    print("Creato controllo_video_meron.json")


if __name__ == "__main__":
    controlla()
