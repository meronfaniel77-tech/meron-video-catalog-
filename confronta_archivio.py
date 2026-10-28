
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from sentence_transformers import SentenceTransformer

FILE_APPLE = Path("episodi_apple.json")
FILE_YOUTUBE = Path("archivio_youtube.json")
FILE_CATALOGO = Path("videos.json")
FILE_RISULTATI = Path("controllo_video_meron.json")

MODELLO = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

STOPWORDS = set("""
the and with from what when where who why how
case story true crime elisa part episode this that
into after before about their there were they have
been will would could some more only just than
il lo la gli le un una uno di del della dei delle
da dal dallo dalla dai in con per che cosa caso
storia parte dopo sono era alla sua suo fatto
hanno quella questo questa quello dove come quando
perche anche tutti tutte essere stato stata dentro
fuori ancora nella nelle nello negli sulla sulle
sullo agli alle dalle dello dell dall
""".split())

GENERICHE = set("""
omicidio assassino ucciso morto morte scomparso
scomparsa madre padre figlia figlio famiglia
marito moglie bambino bambini scuola prigione
segreto matrimonio anni giorni delitto vittima
polizia indagine criminale orrore mistero
mostro assassinio verita nuovo nuova ultimo
notte successo ragazza ragazzo donna uomo
""".split())

TRADUZIONI = {
    "monster": "mostro",
    "sniper": "cecchino",
    "massacre": "massacro",
    "mass4cro": "massacro",
    "butcher": "macellaio",
    "chatbot": "chatbot",
    "pushed": "spinto",
    "push": "spinto",
    "death": "morte",
    "dead": "morto",
    "murder": "omicidio",
    "murdered": "omicidio",
    "killer": "assassino",
    "killed": "ucciso",
    "missing": "scomparsa",
    "disappeared": "scomparsa",
    "disappearance": "scomparsa",
    "daughter": "figlia",
    "son": "figlio",
    "mother": "madre",
    "father": "padre",
    "husband": "marito",
    "wife": "moglie",
    "family": "famiglia",
    "marriage": "matrimonio",
    "wedding": "matrimonio",
    "secret": "segreto",
    "secrets": "segreto",
    "truth": "verita",
    "new": "nuovo",
    "last": "ultimo",
    "final": "ultimo",
    "message": "messaggio",
    "courage": "coraggio",
    "revenge": "vendetta",
    "river": "fiume",
    "nightmare": "incubo",
    "night": "notte",
    "mystery": "mistero",
    "horror": "orrore",
    "school": "scuola",
    "prison": "prigione",
    "child": "bambino",
    "children": "bambini",
    "baby": "bambino",
    "years": "anni",
    "days": "giorni",
    "found": "ritrovato",
    "vanished": "scomparsa",
    "lost": "scomparsa",
    "twins": "gemelle",
    "twin": "gemelle",
    "barn": "fienile",
}

# Varianti italiane e inglesi
EQUIVALENZE = {
    "scomparso": "scomparsa",
    "scomparsi": "scomparsa",
    "mostri": "mostro",
    "massacri": "massacro",
    "nuova": "nuovo",
    "ultimo": "ultimo",
    "ultima": "ultimo",
    "uccisa": "ucciso",
    "assassinata": "omicidio",
    "assassinato": "omicidio",
    "omicidi": "omicidio",
    "morta": "morto",
    "figlie": "figlia",
    "figli": "figlio",
    "bambina": "bambino",
    "bambine": "bambini",
}

def normalizza(testo):
    testo = str(testo or "").lower()

    # Alcune lettere stilizzate usate su YouTube
    testo = testo.replace("ǝ", "e")
    testo = testo.replace("Ǝ", "e")
    testo = testo.replace("с", "c")

    testo = re.sub(
        r"\bmass4cro\b", "massacro", testo
    )
    testo = re.sub(
        r"\bmass4cre\b", "massacre", testo
    )
    testo = re.sub(
        r"\bk[!1]ller\b", "killer", testo
    )

    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        c for c in testo
        if not unicodedata.combining(c)
    )

    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def parole(testo):
    risultato = set()

    for parola in normalizza(testo).split():
        parola = TRADUZIONI.get(parola, parola)
        parola = EQUIVALENZE.get(parola, parola)

        if (
            len(parola) >= 4
            and parola not in STOPWORDS
            and not parola.isdigit()
        ):
            risultato.add(parola)

    return risultato


def numero_parte(titolo):
    testo = normalizza(titolo)

    match = re.search(
        r"\b(?:pt|part|parte)\s*([1-9])\b",
        testo
    )

    return int(match.group(1)) if match else None


def leggi_json(percorso):
    with percorso.open("r", encoding="utf-8") as f:
        return json.load(f)


def controlla():
    dati_apple = leggi_json(FILE_APPLE)
    dati_youtube = leggi_json(FILE_YOUTUBE)
    dati_catalogo = leggi_json(FILE_CATALOGO)

    episodi = dati_apple.get("episodes", [])
    archivio = dati_youtube.get("videos", [])
    catalogo = dati_catalogo.get("videos", {})

    if not isinstance(episodi, list):
        raise ValueError("Archivio Apple non valido")

    if not isinstance(archivio, list):
        raise ValueError("Archivio YouTube non valido")

    if not isinstance(catalogo, dict):
        raise ValueError("Catalogo MerON non valido")

    video = [
        v for v in archivio
        if isinstance(v, dict)
        and isinstance(v.get("url"), str)
        and v["url"].startswith(
            "https://www.youtube.com/watch?v="
        )
        and v.get("title")
    ]

    if not video:
        raise ValueError("Nessun video valido")

    print("MERON - RICONOSCIMENTO BILINGUE V2")
    print("Caricamento modello...")

    modello = SentenceTransformer(MODELLO)

    titoli_apple = [
        str(e.get("titolo", ""))
        for e in episodi
    ]

    titoli_youtube = [
        str(v["title"])
        for v in video
    ]

    # Rimuove la numerazione iniziale degli episodi
    titoli_puliti = [
        re.sub(
            r"^\s*ep\.?\s*\d+\s*[:.\-]?\s*",
            "",
            titolo,
            flags=re.IGNORECASE
        )
        for titolo in titoli_apple
    ]

    print("Analisi Apple...")
    vettori_apple = modello.encode(
        titoli_puliti,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False
    )

    print("Analisi YouTube...")
    vettori_youtube = modello.encode(
        titoli_youtube,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False
    )

    parole_youtube = [
        parole(titolo)
        for titolo in titoli_youtube
    ]

    frequenze = Counter()
    for gruppo in parole_youtube:
        frequenze.update(gruppo)

    risultati = []

    for i, episodio in enumerate(episodi):
        titolo = titoli_apple[i]
        parole_apple = parole(titolo)
        parte_apple = numero_parte(titolo)

        candidati = []

        for j, elemento in enumerate(video):
            titolo_video = titoli_youtube[j]
            parte_video = numero_parte(titolo_video)

            if (
                parte_apple is not None
                and parte_video is not None
                and parte_apple != parte_video
            ):
                continue

            comuni = (
                parole_apple & parole_youtube[j]
            )

            specifiche = comuni - GENERICHE

            rare = {
                p for p in specifiche
                if frequenze[p] <= 3
            }

            similarita = float(
                vettori_apple[i] @ vettori_youtube[j]
            )

            # Le corrispondenze specifiche
            # pesano più della sola somiglianza.
            bonus_specifiche = sum(
                2.5 if frequenze[p] <= 3 else 1.2
                for p in specifiche
            )

            bonus_generiche = min(
                len(comuni & GENERICHE) * 0.2,
                0.6
            )

            punteggio = (
                similarita * 5
                + bonus_specifiche
                + bonus_generiche
            )

            parte_incerta = (
                (parte_apple is None)
                != (parte_video is None)
            )

            if parte_incerta:
                punteggio -= 2.0

            # Non scartiamo i video con scarsa
            # somiglianza semantica se hanno
            # nomi o luoghi coincidenti.
            if not comuni and similarita < 0.60:
                continue

            candidati.append({
                "title": titolo_video,
                "url": elemento["url"],
                "score": round(punteggio, 3),
                "similarity": round(similarita, 4),
                "common": sorted(comuni),
                "title_matches": len(specifiche),
                "rare_matches": len(rare),
                "rare_words": sorted(rare),
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

            # Candidato forte non significa
            # automaticamente approvato.
            if (
                primo["score"] >= 7.0
                and primo["rare_matches"] >= 1
                and not primo["parte_incerta"]
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

    # Evita candidati forti duplicati
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

    gia_presenti = sum(
        str(r["trackId"]) in catalogo
        for r in risultati
    )

    nuovi_forti = sum(
        r["status"] == "CANDIDATO_FORTE"
        and str(r["trackId"]) not in catalogo
        for r in risultati
    )

    print("Episodi Apple:", len(episodi))
    print("Video YouTube:", len(video))
    print("Candidati forti:", forti)
    print("Nuovi candidati forti:", nuovi_forti)
    print("Da verificare:", len(risultati) - forti)
    print("Episodi gia' nel catalogo:", gia_presenti)

    with FILE_RISULTATI.open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(
            {"results": risultati},
            f,
            ensure_ascii=False,
            indent=2
        )
        f.write("\n")

    print("Creato controllo_video_meron.json")


if __name__ == "__main__":
    controlla()
