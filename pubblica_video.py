import json
import math
import os
import tempfile
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Riusa i dizionari completi: non carica il modello bilingue.
from confronta_archivio import GENERICHE, STOPWORDS, TRADUZIONI, normalizza

BASE = Path(__file__).resolve().parent
CONTROLLO = BASE / "controllo_video_meron.json"
CATALOGO = BASE / "videos.json"
REPORT = BASE / "report_pubblicazione.json"

# True: aggiunge i collegamenti.
# False: esegue soltanto la simulazione.
PUBBLICA = True

# I filtri della simulazione V2 restano invariati.
ESCLUSE = (set(STOPWORDS) - {"elisa"}) | set("""
for of to at on by is was are be it its his her she he my your our
has had did do does an as but not out all you us we they them
nel al ai ad ed sul tra fra dei il lo la le gli un una e o a
ha ho si no ne non mi ti ci vi piu gia sia ep pt parte part jr
""".split())

DESCRITTIVE = set(GENERICHE) | {
    traduzione
    for parola, traduzione in TRADUZIONI.items()
    if parola != traduzione
} | set("""
lato oscuro dark side sides light nulla niente davvero siamo stati
fatto fine vita mondo caso casi storia storie racconti puntata puntate
nuovo nuova nuove nuovi serial made italiani mediatici dietro sempre
ultimo ultima ultime vero falsa falso verita mistero mostro
tragedia assurdo assurda scioccante incredibile famoso famosi
scompare ritrovato scomparsa morte giorno giorni anno anni
""".split())

TRADOTTE = {
    parola
    for parola, traduzione in TRADUZIONI.items()
    if parola != traduzione
}


def leggi_json(percorso):
    with percorso.open(encoding="utf-8-sig") as file:
        dati = json.load(file)

    if not isinstance(dati, dict):
        raise ValueError(
            f"Oggetto JSON atteso in {percorso.name}"
        )

    return dati


def titolo_pulito(testo):
    testo = re.sub(
        r"^\s*(?:ep|episodio|episode)\s*\.*\s*\d+\s*[:.\-]?\s*",
        "",
        str(testo or ""),
        flags=re.I
    )

    testo = re.sub(
        r"\s*[|\-]\s*Elisa True Crime\s*$",
        "",
        testo,
        flags=re.I
    )

    return normalizza(testo)


def termini(testo):
    # Mantiene anche nomi brevi e numeri significativi.
    risultato = set()

    pulito = re.sub(
        r"\b(?:pt|part|parte)\s*(?:\d+|iii|ii|iv|vi|v|i)\b",
        "",
        titolo_pulito(testo)
    )

    for parola in pulito.split():
        tradotta = TRADUZIONI.get(parola, parola)

        if (
            (len(tradotta) >= 3 or tradotta.isdigit())
            and tradotta not in ESCLUSE
        ):
            risultato.add(tradotta)

    return risultato


def riferimenti(testo):
    # Indizi distintivi, non un riconoscimento
    # certificato dei nomi propri.
    return {
        parola
        for parola in titolo_pulito(testo).split()
        if len(parola) >= 3
        and not parola.isdigit()
        and parola not in ESCLUSE
        and parola not in DESCRITTIVE
        and parola not in TRADOTTE
    }


def parte(testo):
    match = re.search(
        r"\b(?:pt|part|parte)\s*(\d+|iii|ii|iv|vi|v|i)\b",
        titolo_pulito(testo)
    )

    if not match:
        return None

    valore = match.group(1)

    if valore.isdigit():
        return int(valore)

    return {
        "i": 1,
        "ii": 2,
        "iii": 3,
        "iv": 4,
        "v": 5,
        "vi": 6
    }[valore]


def aggiornamento(testo):
    return bool(
        re.search(
            r"\b(?:aggiornamento|aggiornamenti|update|updates)\b|"
            r"\bnuov[ae] verita\b|\bnew truth\b",
            titolo_pulito(testo)
        )
    )


def youtube_id(url):
    if not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url)

        if parsed.scheme != "https":
            return None

        if (
            parsed.netloc in {
                "www.youtube.com",
                "youtube.com",
                "m.youtube.com"
            }
            and parsed.path == "/watch"
        ):
            valori = parse_qs(parsed.query).get("v", [])
            valore = valori[0] if len(valori) == 1 else ""

        elif parsed.netloc == "youtu.be":
            valore = parsed.path.removeprefix("/")

        else:
            return None

        if re.fullmatch(r"[A-Za-z0-9_-]{11}", valore):
            return valore

        return None

    except ValueError:
        return None


def numero(valore):
    if (
        isinstance(valore, bool)
        or not isinstance(valore, (int, float))
    ):
        return None

    return float(valore) if math.isfinite(valore) else None


def verifica(episodio, video, id_usati, conteggi):
    titolo = episodio.get("episode", "")
    titolo_video = video.get("title", "")
    identificativo = str(episodio.get("trackId") or "")
    video_id = youtube_id(video.get("url"))
    motivi = []

    if (
        not identificativo.isdigit()
        or not titolo
        or not titolo_video
    ):
        motivi.append("Dati incompleti")

    if video_id is None:
        motivi.append("URL YouTube non valido")

    if video_id in id_usati:
        motivi.append(
            "Video gia collegato a un altro episodio"
        )

    if video_id and conteggi[video_id] > 1:
        motivi.append(
            "Video proposto per piu candidati forti"
        )

    testi = (
        titolo_pulito(titolo)
        + " "
        + titolo_pulito(titolo_video)
    )

    if re.search(r"\btrailer\b", testi):
        motivi.append(
            "Trailer: non associato automaticamente"
        )

    if (
        parte(titolo) != parte(titolo_video)
        or video.get("parte_incerta") is True
    ):
        motivi.append("Parte episodio non confermata")

    if aggiornamento(titolo) != aggiornamento(titolo_video):
        motivi.append(
            "Aggiornamento e versione originale da distinguere"
        )

    parole_apple = termini(titolo)
    parole_video = termini(titolo_video)
    comuni = parole_apple & parole_video

    indizi = (
        riferimenti(titolo)
        & riferimenti(titolo_video)
    )

    copertura = (
        len(comuni) / min(
            len(parole_apple),
            len(parole_video)
        )
        if parole_apple and parole_video
        else 0.0
    )

    identico = (
        bool(titolo_pulito(titolo))
        and titolo_pulito(titolo)
        == titolo_pulito(titolo_video)
    )

    # Criteri di selezione, non probabilita di correttezza.
    regola = None

    if identico:
        regola = "Titolo identico dopo la normalizzazione"

    elif indizi and parole_apple == parole_video:
        regola = (
            "Termini equivalenti e riferimento "
            "distintivo condiviso"
        )

    elif len(indizi) >= 2 and copertura >= 0.60:
        regola = (
            "Almeno due riferimenti distintivi "
            "e copertura sufficiente"
        )

    elif (
        indizi
        and len(comuni) >= 2
        and copertura >= 0.80
    ):
        regola = (
            "Confronto bilingue con riferimento "
            "distintivo e contesto"
        )

    if regola is None:
        motivi.append(
            "Indizi insufficienti per "
            "l'abbinamento automatico"
        )

    score = numero(video.get("score"))

    altri = [
        numero(candidato.get("score"))
        for candidato in episodio.get("candidates", [])
        if isinstance(candidato, dict)
        and youtube_id(candidato.get("url")) != video_id
    ]

    altri = [
        punteggio
        for punteggio in altri
        if punteggio is not None
    ]

    if score is None:
        motivi.append("Punteggio mancante o non valido")

    elif altri and score <= max(altri) * 1.5:
        motivi.append(
            "Margine sul migliore degli altri "
            "candidati insufficiente"
        )

    return {
        "trackId": identificativo,
        "episode": titolo,
        "video": titolo_video,
        "url": video.get("url"),
        "esito": (
            "DA_RIVEDERE"
            if motivi
            else "SUPERA_FILTRI"
        ),
        "regola": regola,
        "termini_comuni": sorted(comuni),
        "riferimenti_condivisi": sorted(indizi),
        "copertura_titolo_piu_breve": round(
            copertura, 3
        ),
        "motivi": motivi
    }


def salva_atomico(percorso, dati):
    """Prepara il JSON completo prima di sostituire il file."""
    contenuto = json.dumps(
        dati,
        ensure_ascii=False,
        indent=2,
        allow_nan=False
    ) + "\n"

    temporaneo = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=percorso.parent,
            prefix=percorso.name + ".",
            suffix=".tmp",
            delete=False
        ) as file:
            temporaneo = Path(file.name)
            file.write(contenuto)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporaneo, percorso)

    finally:
        if temporaneo is not None and temporaneo.exists():
            temporaneo.unlink()


def main():
    # Conserva una fotografia del catalogo prima di lavorarci.
    originale = CATALOGO.read_bytes()
    catalogo = json.loads(
        originale.decode("utf-8-sig")
    )
    controllo = leggi_json(CONTROLLO)

    risultati = controllo.get("results")
    videos = (
        catalogo.get("videos")
        if isinstance(catalogo, dict)
        else None
    )

    if (
        not isinstance(risultati, list)
        or not isinstance(videos, dict)
    ):
        raise ValueError(
            "Formato JSON non valido: catalogo non modificato"
        )

    # Un ID ripetuto nel report non deve causare aggiunte ambigue.
    ids = set()

    for episodio in risultati:
        if not isinstance(episodio, dict):
            raise ValueError("Voce episodio non valida")

        identificativo = str(
            episodio.get("trackId") or ""
        )

        if (
            not identificativo.isdigit()
            or identificativo in ids
        ):
            raise ValueError(
                "ID episodio mancante, non valido o ripetuto"
            )

        ids.add(identificativo)

    forti = [
        episodio
        for episodio in risultati
        if episodio.get("status") == "CANDIDATO_FORTE"
    ]

    id_usati = {
        youtube_id(video.get("youtubeUrl"))
        for video in videos.values()
        if isinstance(video, dict)
    } - {None}

    conteggi = Counter(
        youtube_id(
            episodio["candidates"][0].get("url")
        )
        for episodio in forti
        if isinstance(
            episodio.get("candidates"), list
        )
        and episodio["candidates"]
        and isinstance(
            episodio["candidates"][0], dict
        )
    )

    verifiche = []

    for episodio in forti:
        if str(episodio["trackId"]) in videos:
            continue

        candidati = episodio.get("candidates")

        if (
            not isinstance(candidati, list)
            or not candidati
            or not isinstance(candidati[0], dict)
        ):
            raise ValueError(
                "Candidato forte senza dettagli utilizzabili"
            )

        if (
            not isinstance(episodio.get("episode"), str)
            or not isinstance(
                candidati[0].get("title"), str
            )
        ):
            raise ValueError(
                "Titolo episodio o video non valido"
            )

        verifiche.append(
            verifica(
                episodio,
                candidati[0],
                id_usati,
                conteggi
            )
        )

    selezionati = [
        verifica_video
        for verifica_video in verifiche
        if verifica_video["esito"] == "SUPERA_FILTRI"
    ]

    aggiunte = {}
    data_utc = datetime.now(
        timezone.utc
    ).isoformat()

    for candidato in selezionati:
        episodio_id = candidato["trackId"]
        video_id = youtube_id(candidato["url"])

        # Ultimo controllo: nessuna sovrascrittura.
        if (
            episodio_id in videos
            or episodio_id in aggiunte
            or video_id is None
            or video_id in id_usati
        ):
            raise ValueError(
                "Conflitto nelle aggiunte: catalogo non modificato"
            )

        aggiunte[episodio_id] = {
            "podcast": "Elisa True Crime",
            "episode": candidato["episode"],
            "youtubeUrl": (
                "https://www.youtube.com/watch?v="
                + video_id
            ),
            "verified": False,
            "automaticMatch": True,
            "matchMethod": "controllo-bilingue-2",
            "matchedVideoTitle": candidato["video"],
            "matchRule": candidato["regola"],
            "addedAt": data_utc
        }

        id_usati.add(video_id)

    prima = len(videos)
    aggiunti = 0

    if PUBBLICA and aggiunte:
        # Conserva le voci e gli altri campi gia presenti.
        aggiornato = {
            **catalogo,
            "videos": {
                **videos,
                **aggiunte
            }
        }

        if CATALOGO.read_bytes() != originale:
            raise RuntimeError(
                "Catalogo cambiato durante il controllo: ripetere"
            )

        salva_atomico(CATALOGO, aggiornato)
        aggiunti = len(aggiunte)

    riepilogo = {
        "modalita": (
            "PUBBLICAZIONE_AUTOMATICA"
            if PUBBLICA
            else "SOLO_SIMULAZIONE"
        ),
        "versione": "controllo-bilingue-2",
        "candidati_forti": len(forti),
        "gia_nel_catalogo": (
            len(forti) - len(verifiche)
        ),
        "nuovi_da_esaminare": len(verifiche),
        "superano_filtri": len(selezionati),
        "da_rivedere": (
            len(verifiche) - len(selezionati)
        ),
        "nuovi_collegamenti_aggiunti": aggiunti,
        "totale_catalogo_prima": prima,
        "totale_catalogo_dopo": prima + aggiunti
    }

    frequenze = Counter(
        motivo
        for verifica_video in verifiche
        for motivo in verifica_video["motivi"]
    )

    salva_atomico(
        REPORT,
        {
            "riepilogo": riepilogo,
            "motivi": dict(frequenze),
            "verifiche": verifiche
        }
    )

    print("MERON - PUBBLICAZIONE AUTOMATICA V2")

    for nome, valore in riepilogo.items():
        print(f"{nome}: {valore}")

    print(
        "\nMOTIVI DI REVISIONE "
        "(possono sovrapporsi)"
    )

    for motivo, quanti in frequenze.most_common():
        print(f"{quanti}: {motivo}")

    for candidato in selezionati:
        azione = (
            "AGGIUNTO"
            if PUBBLICA
            else "SELEZIONATO"
        )

        print(
            f"{azione} | "
            f"{candidato['episode']} | "
            f"{candidato['video']}"
        )

    print("Creato:", REPORT.name)

    print(
        "videos.json AGGIORNATO"
        if aggiunti
        else "videos.json NON modificato"
    )

    print(
        "Nuovi collegamenti automatici: "
        "verified resta false."
    )

    print(
        "Disponibilita e contenuto dei video "
        "non verificati online."
    )

    print(
        "Il salvataggio su GitHub avviene "
        "nel successivo passo del workflow."
    )


if __name__ == "__main__":
    main()
