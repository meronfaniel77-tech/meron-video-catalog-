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

# Conserva e riutilizza tutti i dizionari del programma gia installato.
from confronta_archivio import GENERICHE, STOPWORDS, TRADUZIONI

BASE = Path(__file__).resolve().parent
PUBBLICA = os.environ.get("MERON_SIMULAZIONE", "0") != "1"
CERCA_ITALIANO = os.environ.get("MERON_TITOLI_ITALIANI", "1") != "0"
CHANNEL_ID = "UCxH0MkY6v0sjZzmMgW9TSRQ"

# Integrazioni ai dizionari esistenti, non loro sostituzioni.
TRAD = dict(TRADUZIONI)
TRAD.update({
    "new": "nuova", "latest": "nuova", "truth": "verita",
    "happened": "successo", "happens": "successo", "that": "quella",
    "night": "notte", "macabre": "macabro", "plan": "piano",
    "twins": "gemelle", "twin": "gemelle", "cult": "setta",
    "zizians": "ziziani", "gypsy": "gipsy", "scheme": "schema",
    "secrets": "segreti", "personalities": "personalita",
    "freeway": "superstrada", "phantom": "fantasma",
    "hiding": "nascondeva", "wanted": "voleva", "ice": "ghiaccio",
    "lady": "donna", "whole": "tutta", "dark": "oscuro",
    "side": "lato", "sides": "lato", "light": "luce",
    "killers": "assassini", "monster": "mostro", "butcher": "macellaio",
    "sniper": "cecchino", "massacre": "massacro", "barn": "fienile",
    "letters": "lettere", "books": "libri", "lies": "bugie",
    "other": "altre", "death": "morte", "pushed": "spinto",
    "courage": "coraggio", "last": "ultimo", "message": "messaggio",
    "everything": "tutto", "seemed": "sembrava", "decided": "deciso",
    "already": "gia",
})
# Queste parole vengono conservate: distinguono aggiornamenti e casi.
STOP = (set(STOPWORDS) - {"elisa", "nuova", "new", "truth", "verita",
        "notte", "successo", "morte", "giorni", "ed"}) | set("""
for of to at on by is was are be it its his her she he my your our has had
an as but out all you us we they them nel al ai ad sul tra fra ha ho
si non mi ti ci vi piu gia sia ep pt jr this that what which cos lei noi
""".split())
DESCRITTIVE = set(GENERICHE) | {k for k, v in TRAD.items() if k != v} | {v for k, v in TRAD.items() if k != v} | set("""
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
PART_RE = re.compile(r"\b(?:pt|part|parte)\s*(\d+|viii|vii|vi|iv|iii|ii|v|i)\b")


def leggi(nome):
    with (BASE / nome).open(encoding="utf-8-sig") as f:
        dati = json.load(f)
    if not isinstance(dati, dict):
        raise ValueError(f"Formato non valido: {nome}")
    return dati


def salva(nome, dati):
    destinazione = BASE / nome
    contenuto = json.dumps(dati, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporaneo = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=BASE,
                                         suffix=".tmp", delete=False) as f:
            temporaneo = Path(f.name)
            f.write(contenuto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporaneo, destinazione)
    finally:
        if temporaneo is not None and temporaneo.exists():
            temporaneo.unlink()


def video_id(url):
    if not isinstance(url, str):
        return None
    try:
        p = urlparse(url)
        if p.scheme != "https":
            return None
        if p.netloc in {"www.youtube.com", "youtube.com", "m.youtube.com"} and p.path == "/watch":
            valori = parse_qs(p.query).get("v", [])
            v = valori[0] if len(valori) == 1 else ""
        elif p.netloc == "youtu.be":
            v = p.path.lstrip("/")
        else:
            return None
        return v if re.fullmatch(r"[A-Za-z0-9_-]{11}", v) else None
    except ValueError:
        return None


def normalizza(testo):
    testo = str(testo or "")

    # Corregge una l minuscola usata come I dentro una parola
    # quasi tutta maiuscola, prima di perdere questa informazione.
    def correggi_i_stilizzata(match):
        parola = match.group(0)
        resto = parola.replace("l", "")
        if (
            "l" in parola
            and len(resto) >= 4
            and resto.isupper()
            and all(c.isupper() for c in resto if c.isalpha())
        ):
            return parola.replace("l", "I")
        return parola

    testo = re.sub(r"[^\W\d_]+", correggi_i_stilizzata, testo)
    testo = testo.casefold()
    testo = testo.translate(str.maketrans({
        "\u01dd": "e", "\u018e": "e", "\u2200": "a",
        "\u044f": "r", "\u0441": "c", "\u0438": "n",
        "\u043e": "o", "\u0430": "a",
    }))

    # Mantiene tutte le correzioni specifiche gia presenti.
    for originale, corretto in {
        "k!ller": "killer", "l!sa": "lisa",
        "c!rce0": "circeo", "assasslna": "assassina",
        "madlson": "madison"
    }.items():
        testo = testo.replace(originale, corretto)

    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        c for c in testo if not unicodedata.combining(c)
    )

    # Il punto esclamativo vale I solo DENTRO una parola.
    testo = re.sub(r"(?<=[a-z])!(?=[a-z])", "i", testo)

    def correggi_cifre(match):
        parola = match.group(0)
        # Non altera 764, 105, gli anni o sigle come PT10.
        if parola.isdigit() or re.fullmatch(
            r"(?:pt|part|parte|ep)\d+", parola
        ):
            return parola
        if re.search(r"[a-z]", parola):
            return parola.translate(str.maketrans({
                "0": "o", "4": "a", "3": "e"
            }))
        return parola

    # Include anche lo zero INIZIALE: 0DI0 diventa odio.
    testo = re.sub(r"\b[a-z0-9]+\b", correggi_cifre, testo)
    testo = re.sub(
        r"\b([a-z])\.\s*([a-z])(?:\.(?=\W|$)|\b)",
        r"\1\2", testo
    )
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()

def dettagli(titolo):
    testo = re.sub(r"^\s*(?:ep|episodio|episode)\s*\.*\s*\d+\s*[:.\-]?\s*",
                   "", str(titolo or ""), flags=re.I)
    testo = re.sub(r"\s*[|\-]\s*Elisa True Crime\s*$", "", testo, flags=re.I)
    testo = normalizza(testo)
    testo = re.sub(r"\bvanished without a trace\b", "scomparsa nel nulla", testo)
    parti = PART_RE.findall(testo)
    romani = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}
    parte = int(parti[0]) if parti and parti[0].isdigit() else romani.get(parti[0]) if parti else None
    corpo = PART_RE.sub(" ", testo)
    lista = [p for p in corpo.split() if p not in STOP and len(p) >= 2]
    termini = {TRAD.get(p, p) for p in lista} - STOP
    indizi = {p for p in lista if p not in DESCRITTIVE and not p.isdigit()}
    aggiornamento = bool(re.search(r"\b(?:aggiornamento|update|updates)\b|\bnew truth\b|\bnuova verita\b", testo))
    return {"testo": testo, "termini": termini, "indizi": indizi,
            "parte": parte, "aggiornamento": aggiornamento,
            "trailer": "trailer" in corpo.split()}


def titoli_italiani(archivio):
    if not CERCA_ITALIANO:
        return "DISATTIVATO", 0
    comando = [sys.executable, "-m", "yt_dlp", "--ignore-config",
        "--flat-playlist", "--skip-download", "--dump-single-json",
        "--socket-timeout", "10", "--retries", "1", "--extractor-retries", "1",
        "--extractor-args", "youtube:lang=it",
        f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"]
    try:
        r = subprocess.run(comando, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if r.returncode:
            raise RuntimeError(r.stderr[-300:])
        dati = json.loads(r.stdout)
        if dati.get("channel_id") and dati["channel_id"] != CHANNEL_ID:
            raise ValueError("Canale inatteso")
        entrate = dati.get("entries")
        if not isinstance(entrate, list) or not entrate:
            raise ValueError("Elenco vuoto")
        nuovi = 0
        for v in entrate:
            if not isinstance(v, dict) or v.get("id") not in archivio:
                continue
            titolo = v.get("title")
            if isinstance(titolo, str) and titolo.strip() and titolo not in archivio[v["id"]]["titoli"]:
                archivio[v["id"]]["titoli"].append(titolo)
                nuovi += 1
        return "RIUSCITO_TITOLI_NON_GARANTITI_IN_ITALIANO", nuovi
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("Titoli in italiano non recuperati; uso l'archivio disponibile:", str(exc)[:250])
        return "NON_DISPONIBILE", 0


def valuta(a, b, titolo, vid):
    comuni = a["termini"] & b["termini"]
    indizi = a["indizi"] & b["indizi"]
    cop_a = len(comuni) / len(a["termini"]) if a["termini"] else 0
    cop_b = len(comuni) / len(b["termini"]) if b["termini"] else 0
    livello, regola = 0, "Indizi insufficienti"
    if a["testo"] == b["testo"] and len(a["testo"].split()) >= 3:
        livello, regola = 4, "Titolo completo coincidente"
    elif a["termini"] == b["termini"] and len(comuni) >= 2 and (indizi or any(x.isdigit() for x in comuni)):
        livello, regola = 3, "Titoli equivalenti con nomi o numeri distintivi"
    elif len(indizi) >= 2 and min(cop_a, cop_b) >= 0.35:
        livello, regola = 2, "Almeno due indizi distintivi e contesto coerente"
    elif indizi and len(comuni) >= 3 and min(cop_a, cop_b) >= 0.75:
        livello, regola = 2, "Indizio distintivo e forte copertura bilingue"
    # La descrizione aggiunge indizi solo se un riferimento coincide gia nel titolo.
    supporto = a.get("descr_indizi", set()) & b["indizi"]
    if livello < 2 and indizi and len(indizi | supporto) >= 2 and b["indizi"] <= (indizi | supporto):
        livello, regola = 2, "Riferimento nel titolo confermato dalla descrizione Apple"
    # La stessa storia non prova la corrispondenza della singola parte.
    blocchi = []
    if a["trailer"] or b["trailer"]:
        blocchi.append("TRAILER")
    if a["parte"] != b["parte"]:
        blocchi.append("PARTI_NON_ALLINEATE")
    if a["aggiornamento"] != b["aggiornamento"]:
        blocchi.append("VERSIONI_DIVERSE")
    return {"videoId": vid, "title": titolo,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "livello": livello, "regola": regola, "blocchi": blocchi,
        "indizi": sorted(indizi), "comuni": sorted(comuni),
        "copertura": round(min(cop_a, cop_b), 3),
        "priorita": (livello, len(indizi), round(min(cop_a, cop_b), 3), len(comuni))}



def chiave_caso_condiviso(titolo):
    """Identifica lo stesso caso ignorando soltanto PT.1 e PT.2."""
    info = dettagli(titolo)
    base = PART_RE.sub(" ", info["testo"])
    return re.sub(r"\s+", " ", base).strip(), info["parte"]


def collega_video_del_caso(esiti, usati, archivio):
    """Permette UN video sul caso per entrambe le parti, con criteri precisi.

    Non afferma che il video copra integralmente entrambe le puntate.
    Blocca i video che riportano un numero di parte esplicito.
    """
    gruppi = defaultdict(list)
    gia_assegnati = {
        voce["selezionato"]["videoId"]
        for voce in esiti
        if voce["esito"] == "SELEZIONATO" and voce["selezionato"]
    }

    for voce in esiti:
        if voce["esito"] != "PARTI_NON_ALLINEATE":
            continue
        caso, numero_parte = chiave_caso_condiviso(voce["episode"])
        if caso and numero_parte in (1, 2):
            gruppi[caso].append((numero_parte, voce))

    proposte_coppie = []
    for caso, gruppo in gruppi.items():
        if len(gruppo) != 2 or {p for p, _ in gruppo} != {1, 2}:
            continue
        gruppo.sort(key=lambda e: e[0])
        prima, seconda = gruppo[0][1], gruppo[1][1]
        candidati = []
        for episodio in (prima, seconda):
            opzioni = episodio.get("proposte", [])
            if not opzioni or not isinstance(opzioni[0], dict):
                break
            migliore = opzioni[0]
            # Deve essere l'unico video con sufficiente supporto per il caso.
            if (migliore.get("livello", 0) < 2
                    or migliore.get("blocchi") != ["PARTI_NON_ALLINEATE"]
                    or len(migliore.get("indizi", [])) < 2
                    or any(
                        x.get("livello", 0) >= migliore["livello"]
                        and x.get("videoId") != migliore.get("videoId")
                        for x in opzioni[1:] if isinstance(x, dict)
                    )):
                break
            candidati.append(migliore)
        if len(candidati) != 2:
            continue
        a, b = candidati
        vid = a.get("videoId")
        if (not vid or vid != b.get("videoId") or vid not in archivio
                or vid in usati or vid in gia_assegnati
                or dettagli(a.get("title", ""))["parte"] is not None
                or dettagli(b.get("title", ""))["parte"] is not None):
            continue
        proposte_coppie.append((vid, prima, seconda, a, b))

    # Lo stesso video non puo essere usato per due CASI diversi.
    contatore = Counter(vid for vid, *_ in proposte_coppie)
    aggiunte = 0
    for vid, prima, seconda, a, b in proposte_coppie:
        if contatore[vid] != 1:
            continue
        for episodio, candidato in ((prima, a), (seconda, b)):
            episodio["esito"] = "VIDEO_DEL_CASO_CONDIVISO"
            episodio["selezionato"] = candidato
            episodio["sharedCaseVideo"] = True
            # Confermato dall'utente per Gacy; sugli altri e' una proposta.
            episodio["sharedCoverageConfirmed"] = (vid == "NGnCtty6flw")
            aggiunte += 1
    return aggiunte // 2

def main():
    percorso = BASE / "videos.json"
    originale = percorso.read_bytes()
    catalogo = json.loads(originale.decode("utf-8-sig"))
    episodi = leggi("episodi_apple.json").get("episodes")
    video = leggi("archivio_youtube.json").get("videos")
    controllo = leggi("controllo_video_meron.json")
    risultati = controllo.get("results")
    salvati = catalogo.get("videos") if isinstance(catalogo, dict) else None
    if not isinstance(episodi, list) or not episodi or not isinstance(video, list) or not video or not isinstance(salvati, dict) or not isinstance(risultati, list):
        raise ValueError("Archivi mancanti, vuoti o non validi: catalogo intatto")
    ids = [str(e.get("id", "")) if isinstance(e, dict) else "" for e in episodi]
    if any(not x.isdigit() for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("ID Apple non validi o duplicati: catalogo intatto")
    archivio = {}
    for v in video:
        if not isinstance(v, dict):
            continue
        vid = video_id(v.get("url"))
        if vid and isinstance(v.get("title"), str) and v["title"].strip():
            archivio.setdefault(vid, {"titoli": []})["titoli"].append(v["title"])
    if not archivio:
        raise ValueError("Nessun video utilizzabile")
    lingua, varianti = titoli_italiani(archivio)
    for v in archivio.values():
        v["dettagli"] = [(t, dettagli(t)) for t in dict.fromkeys(v["titoli"])]
    stato_precedente = {str(r.get("trackId")): r.get("status") for r in risultati if isinstance(r, dict)}
    usati = {video_id(v.get("youtubeUrl")) for v in salvati.values() if isinstance(v, dict)} - {None}
    esiti = []
    for e, eid in zip(episodi, ids):
        if eid in salvati:
            continue
        titolo = e.get("titolo", "")
        if not isinstance(titolo, str) or not titolo.strip():
            raise ValueError("Titolo Apple mancante")
        a = dettagli(titolo)
        a["descr_indizi"] = dettagli(e.get("descrizione", ""))["indizi"]
        candidati = []
        for vid, v in archivio.items():
            valutazioni = [valuta(a, b, t, vid) for t, b in v["dettagli"]]
            # Seleziona la migliore variante dello STESSO video.
            c = max(valutazioni, key=lambda x: (not x["blocchi"], x["priorita"]))
            if c["comuni"]:
                candidati.append(c)
        utilizzabili = sorted([c for c in candidati if c["livello"] >= 2 and not c["blocchi"]],
                              key=lambda c: c["priorita"], reverse=True)
        stato, scelto = "DATI_INSUFFICIENTI", None
        if a["trailer"]:
            stato = "TRAILER"
        elif utilizzabili:
            c = utilizzabili[0]
            # Non sceglie arbitrariamente tra due video sullo stesso caso.
            if len(utilizzabili) > 1 and utilizzabili[1]["livello"] >= c["livello"]:
                stato = "PIU_VIDEO_COMPATIBILI"
            elif c["videoId"] in usati:
                stato = "VIDEO_GIA_ASSOCIATO"
            else:
                stato, scelto = "SELEZIONATO", c
        elif any(c["livello"] >= 2 and "PARTI_NON_ALLINEATE" in c["blocchi"] for c in candidati):
            stato = "PARTI_NON_ALLINEATE"
        elif any(c["livello"] >= 2 and "VERSIONI_DIVERSE" in c["blocchi"] for c in candidati):
            stato = "VERSIONI_DIVERSE"
        proposte = sorted(candidati, key=lambda c: c["priorita"], reverse=True)[:5]
        esiti.append({"trackId": eid, "episode": titolo, "stato_precedente": stato_precedente.get(eid),
                      "esito": stato, "selezionato": scelto, "proposte": proposte})
    assegnazioni = defaultdict(list)
    for r in esiti:
        if r["esito"] == "SELEZIONATO":
            assegnazioni[r["selezionato"]["videoId"]].append(r)
    for gruppo in assegnazioni.values():
        if len(gruppo) > 1:
            for r in gruppo:
                r["esito"] = "VIDEO_CONDIVISO_DA_DISTINGUERE"
                r["selezionato"] = None
    # Dopo il controllo standard, valuta le coppie PT.1 / PT.2
    # che puntano al medesimo video privo di numerazione.
    coppie_video_del_caso = collega_video_del_caso(esiti, usati, archivio)

    aggiunte = {}
    data = datetime.now(timezone.utc).isoformat()
    for r in esiti:
        if r["esito"] not in ("SELEZIONATO", "VIDEO_DEL_CASO_CONDIVISO"):
            continue
        c = r["selezionato"]
        condiviso = r["esito"] == "VIDEO_DEL_CASO_CONDIVISO"
        record = {"podcast": "Elisa True Crime", "episode": r["episode"],
            "youtubeUrl": c["url"], "verified": False, "automaticMatch": True,
            "matchMethod": "recupero-tutti-v4" if condiviso else "recupero-tutti-v3",
            "matchedVideoTitle": c["title"],
            "matchRule": ("Stesso video ufficiale del caso per PT.1 e PT.2; "
                          "copertura intera da confermare" if condiviso
                          else c["regola"]), "addedAt": data}
        if condiviso:
            record.update({
                "sharedCaseVideo": True,
                "videoRelation": "video_del_caso",
                "videoLabel": "Guarda il video sul caso",
                "coversBothPartsConfirmed": r["sharedCoverageConfirmed"],
            })
        aggiunte[r["trackId"]] = record
    nuovi = len(aggiunte) if PUBBLICA else 0
    conteggi = Counter(r["esito"] for r in esiti)
    riepilogo = {"modalita": "PUBBLICAZIONE_AUTOMATICA" if PUBBLICA else "SOLO_SIMULAZIONE",
        "versione": "recupero-tutti-v4", "episodi_apple": len(episodi),
        "coppie_pt1_pt2_con_video_del_caso": coppie_video_del_caso,
        "episodi_collegati_a_video_del_caso": 2 * coppie_video_del_caso,
        "video_archivio": len(archivio), "recupero_titoli_italiani": lingua,
        "varianti_aggiuntive": varianti, "episodi_gia_collegati": len(episodi) - len(esiti),
        "episodi_senza_collegamento_esaminati": len(esiti),
        "selezionati": len(aggiunte),
        "recuperati_da_DA_VERIFICARE": sum(r["esito"] == "SELEZIONATO" and r["stato_precedente"] == "DA_VERIFICARE" for r in esiti),
        "nuovi_collegamenti_aggiunti": nuovi,
        "totale_catalogo_prima": len(salvati), "totale_catalogo_dopo": len(salvati) + nuovi,
        "episodi_senza_collegamento_dopo": len(esiti) - nuovi, "motivi_attesa": dict(conteggi)}
    if PUBBLICA and aggiunte:
        if percorso.read_bytes() != originale:
            raise RuntimeError("Catalogo modificato durante il controllo: nessuna scrittura")
        salva("videos.json", {**catalogo, "videos": {**salvati, **aggiunte}})
    report = {"riepilogo": riepilogo, "verifiche": esiti}
    salva("report_pubblicazione.json", report)
    # Il workflow carica gia questo file: include anche l'esito finale aggiornato.
    controllo["recupero_v3"] = report
    salva("controllo_video_meron.json", controllo)
    print("MERON - RECUPERO VIDEO CONDIVISI PT.1 / PT.2 V4")
    for nome, valore in riepilogo.items():
        print(f"{nome}: {valore}")
    for r in esiti:
        c = r["selezionato"]
        print(f"{r['esito']} | {r['episode']}" + (f" | {c['title']}" if c else ""))
    print("Un video del caso puo apparire in entrambe le parti, senza")
    print("confermare automaticamente che il contenuto copra entrambe.")
    print("Nessuna voce precedente eliminata o sovrascritta. verified resta false.")
    print("Titoli compatibili non provano contenuti identici o riproducibilita.")
    print("Il passo successivo del workflow salva videos.json su GitHub.")


if __name__ == "__main__":
    main()
