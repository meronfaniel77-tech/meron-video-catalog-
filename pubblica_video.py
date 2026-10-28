import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Riutilizza tutti i dizionari del programma gia installato.
from confronta_archivio import GENERICHE, STOPWORDS, TRADUZIONI

BASE = Path(__file__).resolve().parent

# Per una simulazione si puo impostare MERON_SIMULAZIONE=1.
PUBBLICA = os.environ.get("MERON_SIMULAZIONE", "0") != "1"

# Il recupero italiano e' facoltativo: se fallisce,
# il programma continua con l'archivio disponibile.
CERCA_ITALIANO = (
    os.environ.get("MERON_TITOLI_ITALIANI", "1") != "0"
)

CHANNEL_ID = "UCxH0MkY6v0sjZzmMgW9TSRQ"

# Integrazioni ai dizionari esistenti, non loro sostituzioni.
TRAD = dict(TRADUZIONI)

TRAD.update({
    "new": "nuova",
    "latest": "nuova",
    "truth": "verita",
    "happened": "successo",
    "happens": "successo",
    "that": "quella",
    "night": "notte",
    "macabre": "macabro",
    "plan": "piano",
    "twins": "gemelle",
    "twin": "gemelle",
    "cult": "setta",
    "zizians": "ziziani",
    "gypsy": "gipsy",
    "scheme": "schema",
    "secrets": "segreti",
    "personalities": "personalita",
    "freeway": "superstrada",
    "phantom": "fantasma",
    "hiding": "nascondeva",
    "wanted": "voleva",
    "ice": "ghiaccio",
    "lady": "donna",
    "whole": "tutta",
    "dark": "oscuro",
    "side": "lato",
    "sides": "lato",
    "light": "luce",
    "killers": "assassini",
    "monster": "mostro",
    "butcher": "macellaio",
    "sniper": "cecchino",
    "massacre": "massacro",
    "barn": "fienile",
    "letters": "lettere",
    "books": "libri",
    "lies": "bugie",
    "other": "altre",
    "death": "morte",
    "pushed": "spinto",
    "courage": "coraggio",
    "last": "ultimo",
    "message": "messaggio",
    "everything": "tutto",
    "seemed": "sembrava",
    "decided": "deciso",
    "already": "gia",
})

# Conserva anche parole che distinguono versioni diverse
# e nomi brevi come Ed.
STOP = (
    set(STOPWORDS)
    - {
        "elisa", "nuova", "new", "truth", "verita",
        "notte", "successo", "morte", "giorni", "ed"
    }
) | set("""
for of to at on by is was are be it its his her she he my your our has had
an as but out all you us we they them nel al ai ad sul tra fra ha ho
si non mi ti ci vi piu gia sia ep pt jr this that what which cos lei noi
""".split())

DESCRITTIVE = (
    set(GENERICHE)
    | {k for k, v in TRAD.items() if k != v}
    | {v for k, v in TRAD.items() if k != v}
    | set("""
lato oscuro luce nulla niente davvero siamo stati fatto fine vita mondo
caso casi storia storie racconti puntata puntate nuovo nuove nuovi
serial made italiani mediatici dietro sempre ultimo ultima ultime vero
falsa falso mistero mostro tragedia assurdo assurda scioccante incredibile
famoso famosi scompare ritrovato scomparsa morte giorno giorni anno anni
suo suoi loro mamma uomo donna piccolo piccola bambini amica amante
assassina assassino crimine delitto verita nuova quella notte successo
orrore inquietante terribile misterioso misteriosi nascosto nascosta
profondo grande prima dopo durante soltanto solo mente dentro fuori
setta sparizione schiava vittima vittime morte morto morta ucciso uccisa
shot mr mrs full entire complete crimes bambini bambine proprio stessa
aggiornamento update inedito intervista con senza vita segreti segreto
famiglia famigliare celebrity edition supersnatural supernatural
""".split())
)

PART_RE = re.compile(
    r"\b(?:pt|part|parte)\s*(\d+|viii|vii|vi|iv|iii|ii|v|i)\b"
)


def leggi(nome):
    with (BASE / nome).open(encoding="utf-8-sig") as file:
        dati = json.load(file)

    if not isinstance(dati, dict):
        raise ValueError(f"Formato non valido: {nome}")

    return dati


def salva(nome, dati):
    destinazione = BASE / nome

    contenuto = json.dumps(
        dati,
        ensure_ascii=False,
        indent=2,
        allow_nan=False
    ) + "\n"

    temporaneo = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=BASE,
            suffix=".tmp",
            delete=False
        ) as file:
            temporaneo = Path(file.name)
            file.write(contenuto)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporaneo, destinazione)

    finally:
        if temporaneo is not None and temporaneo.exists():
            temporaneo.unlink()


def video_id(url):
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
            valore = parsed.path.lstrip("/")

        else:
            return None

        if re.fullmatch(r"[A-Za-z0-9_-]{11}", valore):
            return valore

        return None

    except ValueError:
        return None


def normalizza(testo):
    testo = str(testo or "").casefold()

    # Caratteri stilizzati presenti nei titoli.
    testo = testo.translate(str.maketrans({
        "\u01dd": "e",
        "\u018e": "e",
        "\u2200": "a",
        "\u044f": "r",
        "\u0441": "c",
        "\u0438": "n",
        "\u043e": "o",
        "\u0430": "a",
    }))

    correzioni = {
        "k!ller": "killer",
        "l!sa": "lisa",
        "c!rce0": "circeo",
        "assasslna": "assassina",
        "madlson": "madison",
    }

    for originale, corretto in correzioni.items():
        testo = testo.replace(originale, corretto)

    # Corregge numeri dentro le parole, non numeri
    # autonomi come 764.
    testo = re.sub(
        r"[a-z][a-z0-9!]*[a-z0-9]",
        lambda match: match[0].translate(
            str.maketrans({
                "0": "o",
                "4": "a",
                "3": "e",
                "!": "i"
            })
        ),
        testo
    )

    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        carattere
        for carattere in testo
        if not unicodedata.combining(carattere)
    )

    # Conserva iniziali come H.H. e O.J.
    testo = re.sub(
        r"\b([a-z])\.\s*([a-z])(?:\.(?=\W|$)|\b)",
        r"\1\2",
        testo
    )

    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def dettagli(titolo):
    testo = re.sub(
        r"^\s*(?:ep|episodio|episode)\s*\.*\s*\d+\s*[:.\-]?\s*",
        "",
        str(titolo or ""),
        flags=re.I
    )

    testo = re.sub(
        r"\s*[|\-]\s*Elisa True Crime\s*$",
        "",
        testo,
        flags=re.I
    )

    testo = normalizza(testo)

    testo = re.sub(
        r"\bvanished without a trace\b",
        "scomparsa nel nulla",
        testo
    )

    parti = PART_RE.findall(testo)

    romani = {
        "i": 1, "ii": 2, "iii": 3, "iv": 4,
        "v": 5, "vi": 6, "vii": 7, "viii": 8
    }

    parte = None

    if parti:
        parte = (
            int(parti[0])
            if parti[0].isdigit()
            else romani.get(parti[0])
        )

    corpo = PART_RE.sub(" ", testo)

    lista = [
        parola
        for parola in corpo.split()
        if parola not in STOP and len(parola) >= 2
    ]

    termini = {
        TRAD.get(parola, parola)
        for parola in lista
    } - STOP

    indizi = {
        parola
        for parola in lista
        if parola not in DESCRITTIVE
        and not parola.isdigit()
    }

    aggiornamento = bool(re.search(
        r"\b(?:aggiornamento|update|updates)\b|"
        r"\bnew truth\b|\bnuova verita\b",
        testo
    ))

    return {
        "testo": testo,
        "termini": termini,
        "indizi": indizi,
        "parte": parte,
        "aggiornamento": aggiornamento,
        "trailer": "trailer" in corpo.split()
    }


def titoli_italiani(archivio):
    if not CERCA_ITALIANO:
        return "DISATTIVATO", 0

    comando = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--flat-playlist",
        "--skip-download",
        "--dump-single-json",
        "--socket-timeout", "10",
        "--retries", "1",
        "--extractor-retries", "1",
        "--extractor-args", "youtube:lang=it",
        f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"
    ]

    try:
        risultato = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120
        )

        if risultato.returncode:
            raise RuntimeError(risultato.stderr[-300:])

        dati = json.loads(risultato.stdout)

        if (
            dati.get("channel_id")
            and dati["channel_id"] != CHANNEL_ID
        ):
            raise ValueError("Canale inatteso")

        entrate = dati.get("entries")

        if not isinstance(entrate, list) or not entrate:
            raise ValueError("Elenco vuoto")

        nuovi = 0

        for video in entrate:
            if (
                not isinstance(video, dict)
                or video.get("id") not in archivio
            ):
                continue

            titolo = video.get("title")
            titoli = archivio[video["id"]]["titoli"]

            if (
                isinstance(titolo, str)
                and titolo.strip()
                and titolo not in titoli
            ):
                titoli.append(titolo)
                nuovi += 1

        return "RIUSCITO_TITOLI_NON_GARANTITI_IN_ITALIANO", nuovi

    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.TimeoutExpired
    ) as errore:
        print(
            "Titoli in italiano non recuperati; "
            "uso l'archivio disponibile:",
            str(errore)[:250]
        )

        return "NON_DISPONIBILE", 0


def valuta(apple, youtube, titolo_video, identificativo):
    comuni = apple["termini"] & youtube["termini"]
    indizi = apple["indizi"] & youtube["indizi"]

    copertura_apple = (
        len(comuni) / len(apple["termini"])
        if apple["termini"]
        else 0
    )

    copertura_video = (
        len(comuni) / len(youtube["termini"])
        if youtube["termini"]
        else 0
    )

    copertura = min(copertura_apple, copertura_video)

    livello = 0
    regola = "Indizi insufficienti"

    if (
        apple["testo"] == youtube["testo"]
        and len(apple["testo"].split()) >= 3
    ):
        livello = 4
        regola = "Titolo completo coincidente"

    elif (
        apple["termini"] == youtube["termini"]
        and len(comuni) >= 2
        and (
            indizi
            or any(parola.isdigit() for parola in comuni)
        )
    ):
        livello = 3
        regola = (
            "Titoli equivalenti con nomi "
            "o numeri distintivi"
        )

    elif len(indizi) >= 2 and copertura >= 0.35:
        livello = 2
        regola = (
            "Almeno due indizi distintivi "
            "e contesto coerente"
        )

    elif (
        indizi
        and len(comuni) >= 3
        and copertura >= 0.75
    ):
        livello = 2
        regola = (
            "Indizio distintivo e forte copertura bilingue"
        )

    # La descrizione aiuta soltanto quando un riferimento
    # coincide gia nel titolo.
    supporto = (
        apple.get("descr_indizi", set())
        & youtube["indizi"]
    )

    if (
        livello < 2
        and indizi
        and len(indizi | supporto) >= 2
        and youtube["indizi"] <= (indizi | supporto)
    ):
        livello = 2
        regola = (
            "Riferimento nel titolo confermato "
            "dalla descrizione Apple"
        )

    blocchi = []

    if apple["trailer"] or youtube["trailer"]:
        blocchi.append("TRAILER")

    # Stesso caso non significa stessa parte.
    if apple["parte"] != youtube["parte"]:
        blocchi.append("PARTI_NON_ALLINEATE")

    if apple["aggiornamento"] != youtube["aggiornamento"]:
        blocchi.append("VERSIONI_DIVERSE")

    return {
        "videoId": identificativo,
        "title": titolo_video,
        "url": (
            "https://www.youtube.com/watch?v="
            + identificativo
        ),
        "livello": livello,
        "regola": regola,
        "blocchi": blocchi,
        "indizi": sorted(indizi),
        "comuni": sorted(comuni),
        "copertura": round(copertura, 3),
        "priorita": (
            livello,
            len(indizi),
            round(copertura, 3),
            len(comuni)
        )
    }


def main():
    percorso = BASE / "videos.json"
    originale = percorso.read_bytes()

    catalogo = json.loads(
        originale.decode("utf-8-sig")
    )

    episodi = leggi("episodi_apple.json").get("episodes")
    video = leggi("archivio_youtube.json").get("videos")
    controllo = leggi("controllo_video_meron.json")
    risultati = controllo.get("results")

    salvati = (
        catalogo.get("videos")
        if isinstance(catalogo, dict)
        else None
    )

    if (
        not isinstance(episodi, list)
        or not episodi
        or not isinstance(video, list)
        or not video
        or not isinstance(salvati, dict)
        or not isinstance(risultati, list)
    ):
        raise ValueError(
            "Archivi mancanti, vuoti o non validi: "
            "catalogo intatto"
        )

    ids = [
        str(episodio.get("id", ""))
        if isinstance(episodio, dict)
        else ""
        for episodio in episodi
    ]

    if (
        any(not identificativo.isdigit() for identificativo in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError(
            "ID Apple non validi o duplicati: catalogo intatto"
        )

    archivio = {}

    for elemento in video:
        if not isinstance(elemento, dict):
            continue

        identificativo = video_id(elemento.get("url"))
        titolo = elemento.get("title")

        if (
            identificativo
            and isinstance(titolo, str)
            and titolo.strip()
        ):
            archivio.setdefault(
                identificativo, {"titoli": []}
            )["titoli"].append(titolo)

    if not archivio:
        raise ValueError("Nessun video utilizzabile")

    lingua, varianti = titoli_italiani(archivio)

    for elemento in archivio.values():
        elemento["dettagli"] = [
            (titolo, dettagli(titolo))
            for titolo in dict.fromkeys(elemento["titoli"])
        ]

    stato_precedente = {
        str(risultato.get("trackId")): risultato.get("status")
        for risultato in risultati
        if isinstance(risultato, dict)
    }

    usati = {
        video_id(elemento.get("youtubeUrl"))
        for elemento in salvati.values()
        if isinstance(elemento, dict)
    } - {None}

    esiti = []

    # Esamina TUTTI gli episodi senza collegamento.
    # Non filtra piu soltanto CANDIDATO_FORTE.
    for episodio, episodio_id in zip(episodi, ids):
        if episodio_id in salvati:
            continue

        titolo = episodio.get("titolo", "")

        if not isinstance(titolo, str) or not titolo.strip():
            raise ValueError("Titolo Apple mancante")

        apple = dettagli(titolo)
        apple["descr_indizi"] = dettagli(
            episodio.get("descrizione", "")
        )["indizi"]

        candidati = []

        for identificativo, elemento in archivio.items():
            valutazioni = [
                valuta(apple, youtube, titolo_video, identificativo)
                for titolo_video, youtube in elemento["dettagli"]
            ]

            # Una sola proposta per ogni ID YouTube,
            # anche quando esistono titoli in due lingue.
            candidato = max(
                valutazioni,
                key=lambda valore: (
                    not valore["blocchi"],
                    valore["priorita"]
                )
            )

            if candidato["comuni"]:
                candidati.append(candidato)

        utilizzabili = sorted(
            [
                candidato
                for candidato in candidati
                if candidato["livello"] >= 2
                and not candidato["blocchi"]
            ],
            key=lambda candidato: candidato["priorita"],
            reverse=True
        )

        stato = "DATI_INSUFFICIENTI"
        scelto = None

        if apple["trailer"]:
            stato = "TRAILER"

        elif utilizzabili:
            candidato = utilizzabili[0]

            if (
                len(utilizzabili) > 1
                and utilizzabili[1]["livello"] >= candidato["livello"]
            ):
                stato = "PIU_VIDEO_COMPATIBILI"

            elif candidato["videoId"] in usati:
                stato = "VIDEO_GIA_ASSOCIATO"

            else:
                stato = "SELEZIONATO"
                scelto = candidato

        elif any(
            candidato["livello"] >= 2
            and "PARTI_NON_ALLINEATE" in candidato["blocchi"]
            for candidato in candidati
        ):
            stato = "PARTI_NON_ALLINEATE"

        elif any(
            candidato["livello"] >= 2
            and "VERSIONI_DIVERSE" in candidato["blocchi"]
            for candidato in candidati
        ):
            stato = "VERSIONI_DIVERSE"

        proposte = sorted(
            candidati,
            key=lambda candidato: candidato["priorita"],
            reverse=True
        )[:5]

        esiti.append({
            "trackId": episodio_id,
            "episode": titolo,
            "stato_precedente": stato_precedente.get(episodio_id),
            "esito": stato,
            "selezionato": scelto,
            "proposte": proposte
        })

    # Evita di assegnare automaticamente lo stesso video
    # a due episodi diversi.
    assegnazioni = defaultdict(list)

    for risultato in esiti:
        if risultato["esito"] == "SELEZIONATO":
            identificativo = risultato["selezionato"]["videoId"]
            assegnazioni[identificativo].append(risultato)

    for gruppo in assegnazioni.values():
        if len(gruppo) > 1:
            for risultato in gruppo:
                risultato["esito"] = "VIDEO_CONDIVISO_DA_DISTINGUERE"
                risultato["selezionato"] = None

    aggiunte = {}
    data = datetime.now(timezone.utc).isoformat()

    for risultato in esiti:
        if risultato["esito"] != "SELEZIONATO":
            continue

        candidato = risultato["selezionato"]

        aggiunte[risultato["trackId"]] = {
            "podcast": "Elisa True Crime",
            "episode": risultato["episode"],
            "youtubeUrl": candidato["url"],
            "verified": False,
            "automaticMatch": True,
            "matchMethod": "recupero-tutti-v3",
            "matchedVideoTitle": candidato["title"],
            "matchRule": candidato["regola"],
            "addedAt": data
        }

    nuovi = len(aggiunte) if PUBBLICA else 0
    conteggi = Counter(risultato["esito"] for risultato in esiti)

    riepilogo = {
        "modalita": (
            "PUBBLICAZIONE_AUTOMATICA"
            if PUBBLICA
            else "SOLO_SIMULAZIONE"
        ),
        "versione": "recupero-tutti-v3",
        "episodi_apple": len(episodi),
        "video_archivio": len(archivio),
        "recupero_titoli_italiani": lingua,
        "varianti_aggiuntive": varianti,
        "episodi_gia_collegati": len(episodi) - len(esiti),
        "episodi_senza_collegamento_esaminati": len(esiti),
        "selezionati": len(aggiunte),
        "recuperati_da_DA_VERIFICARE": sum(
            risultato["esito"] == "SELEZIONATO"
            and risultato["stato_precedente"] == "DA_VERIFICARE"
            for risultato in esiti
        ),
        "nuovi_collegamenti_aggiunti": nuovi,
        "totale_catalogo_prima": len(salvati),
        "totale_catalogo_dopo": len(salvati) + nuovi,
        "episodi_senza_collegamento_dopo": len(esiti) - nuovi,
        "motivi_attesa": dict(conteggi)
    }

    if PUBBLICA and aggiunte:
        if percorso.read_bytes() != originale:
            raise RuntimeError(
                "Catalogo modificato durante il controllo: "
                "nessuna scrittura"
            )

        salva(
            "videos.json",
            {
                **catalogo,
                "videos": {
                    **salvati,
                    **aggiunte
                }
            }
        )

    report = {
        "riepilogo": riepilogo,
        "verifiche": esiti
    }

    salva("report_pubblicazione.json", report)

    # Il workflow carica gia questo file:
    # includiamo anche l'esito finale aggiornato.
    controllo["recupero_v3"] = report
    salva("controllo_video_meron.json", controllo)

    print("MERON - RECUPERO DI TUTTI GLI EPISODI V3")

    for nome, valore in riepilogo.items():
        print(f"{nome}: {valore}")

    for risultato in esiti:
        candidato = risultato["selezionato"]

        riga = (
            f"{risultato['esito']} | "
            f"{risultato['episode']}"
        )

        if candidato:
            riga += f" | {candidato['title']}"

        print(riga)

    print(
        "Nessuna voce precedente eliminata o sovrascritta. "
        "verified resta false."
    )

    print(
        "Titoli compatibili non provano contenuti identici "
        "o riproducibilita."
    )

    print(
        "Il passo successivo del workflow salva "
        "videos.json su GitHub."
    )


if __name__ == "__main__":
    main()
