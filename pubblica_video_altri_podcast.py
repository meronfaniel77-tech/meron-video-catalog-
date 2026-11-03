#!/usr/bin/env python3
"""MerON: prepara collegamenti per podcast diversi da Elisa True Crime.

V1: SOLO SIMULAZIONE. Nel primo avvio non cambia mai videos.json.
Utilizza esclusivamente il rapporto appena prodotto da scopri_youtube_altri_podcast.py.
Esclude l'ambiguita' anche quando un video compare fra le proposte DA_VERIFICARE,
non soltanto quando viene conteso da due CANDIDATO_FORTE.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BASE = Path(__file__).resolve().parent
PUBBLICA = True

RE_YT_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
RE_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
RE_APPLE = re.compile(r"[0-9]{5,20}\Z")
MAX_REPORT_HOURS = 48


def load_dict(path):
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError(f"Formato JSON non valido: {path.name}")
    return obj


def youtube_id(url):
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url)
        if p.scheme != "https":
            return None
        if p.netloc in ("www.youtube.com", "youtube.com", "m.youtube.com") and p.path == "/watch":
            ids = parse_qs(p.query).get("v", [])
            ident = ids[0] if len(ids) == 1 else ""
        elif p.netloc == "youtu.be":
            ident = p.path.removeprefix("/") if p.path.count("/") == 1 else ""
        else:
            return None
        return ident if RE_YT_ID.fullmatch(ident) else None
    except ValueError:
        return None


def check_report(report, config):
    if (report.get("mode") != "SOLO_SIMULAZIONE" or
        report.get("version") != "youtube-altri-podcast-v1"):
        raise ValueError("Rapporto YouTube inatteso: pubblicazione bloccata")
    dt = datetime.fromisoformat(str(report.get("generatedAt", "")).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Rapporto senza data UTC: pubblicazione bloccata")
    delta_hours = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
    if delta_hours < -1 or delta_hours > MAX_REPORT_HOURS:
        raise ValueError("Rapporto YouTube non recente: eseguire prima una nuova scansione")
    configured = config.get("podcasts", [])
    shows = report.get("podcasts", [])
    if not isinstance(configured, list) or not configured or not isinstance(shows, list):
        raise ValueError("Elenco podcast mancante")
    if len(configured) != len(shows) or len(configured) != report.get("showsConfigured") or len(shows) != report.get("showsAnalyzed"):
        raise ValueError("Alcuni podcast non analizzati: nessuna pubblicazione")
    if not isinstance(report.get("errors"), list) or report["errors"]:
        raise ValueError("Rapporto con errori: nessuna pubblicazione")
    expected = {}
    for item in configured:
        if not isinstance(item, dict) or not RE_APPLE.fullmatch(str(item.get("appleCollectionId", ""))):
            raise ValueError("Configurazione Apple non valida")
        cid = str(item["appleCollectionId"])
        if cid in expected or not RE_CHANNEL.fullmatch(str(item.get("youtubeChannelId", ""))):
            raise ValueError("Configurazione con ID duplicato o canale non valido")
        expected[cid] = item
    if len(expected) != len(shows):
        raise ValueError("Podcast duplicati nel rapporto")
    strong_n = review_n = 0
    for show in shows:
        if not isinstance(show, dict):
            raise ValueError("Podcast non valido nel rapporto")
        cid = str(show.get("appleCollectionId", ""))
        cfg = expected.get(cid)
        if not cfg or show.get("youtubeChannelId") != cfg["youtubeChannelId"] or show.get("name") != cfg["name"]:
            raise ValueError(f"Podcast o canale non verificato: {cid}")
        props = show.get("proposals", [])
        if not isinstance(props, list):
            raise ValueError("Proposte in formato non valido")
        n = Counter(p.get("status") for p in props if isinstance(p, dict))
        if any(not isinstance(p, dict) or p.get("status") not in ("CANDIDATO_FORTE", "DA_VERIFICARE") for p in props):
            raise ValueError("Stati delle proposte inattesi")
        if n["CANDIDATO_FORTE"] != show.get("strongCandidates") or n["DA_VERIFICARE"] != show.get("toReview"):
            raise ValueError("Conteggi proposte incoerenti")
        if show.get("noCandidate") != show.get("appleEpisodesRead", 0) - len(props):
            raise ValueError("Conteggio episodi Apple incoerente")
        strong_n += n["CANDIDATO_FORTE"]
        review_n += n["DA_VERIFICARE"]
    if strong_n != report.get("totalStrongCandidates") or review_n != report.get("totalToReview"):
        raise ValueError("Conteggi complessivi incoerenti")
    return expected


def competing_claims(report):
    """Per ogni video, traccia puntate che lo reclamano come best o alternativa vicina."""
    claims = defaultdict(list)
    all_best = defaultdict(list)
    for show in report["podcasts"]:
        cid = str(show["appleCollectionId"])
        for p in show["proposals"]:
            tid = str(p.get("trackId", ""))
            best = p.get("best", {})
            if not isinstance(best, dict):
                continue
            vid = best.get("videoId")
            score = best.get("score")
            if isinstance(vid, str) and RE_YT_ID.fullmatch(vid):
                all_best[vid].append((cid, tid, p.get("status"), score))
                claims[vid].append((cid, tid, "prima_scelta"))
            alt = p.get("alternatives", [])
            if not isinstance(alt, list) or not isinstance(score, int):
                continue
            for candidate in alt:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("score"), int):
                    continue
                other_vid = candidate.get("videoId")
                if (isinstance(other_vid, str) and RE_YT_ID.fullmatch(other_vid)
                        and candidate["score"] >= score - 12):
                    claims[other_vid].append((cid, tid, "alternativa_vicina"))
    return claims, all_best


def safe_candidates(report, catalog, config):
    allowed = check_report(report, config)
    saved = catalog.get("videos")
    if not isinstance(saved, dict):
        raise ValueError("videos.json senza mappa 'videos': non modifico il catalogo")
    current_urls = defaultdict(set)
    for key, value in saved.items():
        if isinstance(value, dict):
            vid = youtube_id(value.get("youtubeUrl"))
            if vid:
                current_urls[vid].add(str(key))

    claims, all_best = competing_claims(report)
    by_track = Counter(str(p.get("trackId", "")) for s in report["podcasts"] for p in s["proposals"])
    selected, held, skipped = [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for show in report["podcasts"]:
        cid, channel, name = str(show["appleCollectionId"]), show["youtubeChannelId"], show["name"]
        assert cid in allowed
        for p in show["proposals"]:
            status = p["status"]
            if status != "CANDIDATO_FORTE":
                continue  # 26 casi in report DA_VERIFICARE restano fuori dalla pubblicazione
            tid = str(p.get("trackId", ""))
            best = p.get("best")
            if not isinstance(best, dict):
                held.append({"podcast": name, "trackId": tid, "reason": "VIDEO_NON_VALIDO"})
                continue
            vid = best.get("videoId")
            url = best.get("youtubeUrl")
            duration = best.get("youtubeDurationSeconds")
            score = best.get("score")
            title = p.get("appleTitle")
            yt_title = best.get("youtubeTitle")
            reason = None
            if (not RE_APPLE.fullmatch(tid) or not isinstance(vid, str) or
                not RE_YT_ID.fullmatch(vid) or url != f"https://www.youtube.com/watch?v={vid}"):
                reason = "ID_O_URL_NON_VALIDI"
            elif by_track[tid] != 1:
                reason = "ID_APPLE_DUPLICATO_NEL_RAPPORTO"
            elif not isinstance(score, int) or isinstance(score, bool) or score < 99:
                reason = "PUNTEGGIO_INSUFFICIENTE"
            elif (not isinstance(duration, (int, float)) or isinstance(duration, bool) or
                  not (600 <= duration <= 86400) or best.get("durationConfirmed") is not True):
                reason = "DURATA_NON_CONFERMATA"
            elif (not isinstance(title, str) or not title.strip() or len(title) > 500 or
                  not isinstance(yt_title, str) or not yt_title.strip() or len(yt_title) > 500):
                reason = "TITOLO_NON_VALIDO"
            elif (not isinstance(best.get("commonTokens"), list) or
                  not best["commonTokens"] or not isinstance(best.get("rule"), str)):
                reason = "INDIZI_MANCANTI"
            elif len({(a, b) for a, b, _ in claims[vid]}) != 1:
                reason = "VIDEO_CONTESO_DA_ALTRI_EPISODI_APPLE"
            elif len({(a, b) for a, b, _, _ in all_best[vid]}) != 1:
                reason = "VIDEO_DUPLICATO_NEL_RAPPORTO"
            elif tid in saved:
                previous = saved[tid]
                if isinstance(previous, dict) and youtube_id(previous.get("youtubeUrl")) == vid:
                    reason = "GIA_PRESENTE_STESSO_VIDEO"
                else:
                    reason = "GIA_PRESENTE_ALTRO_VIDEO_NON_SOVRASCRIVERE"
            elif current_urls.get(vid):
                reason = "VIDEO_GIA_UTILIZZATO_NEL_CATALOGO"

            if reason:
                item = {"podcast": name, "appleCollectionId": cid, "trackId": tid,
                        "episode": title, "youtubeTitle": yt_title, "youtubeUrl": url,
                        "score": score, "reason": reason}
                (skipped if reason == "GIA_PRESENTE_STESSO_VIDEO" else held).append(item)
                continue

            record = {
                "podcast": name,
                "episode": title,
                "youtubeUrl": url,
                "verified": False,
                "automaticMatch": True,
                "matchMethod": "youtube-altri-podcast-verifica-incrociata-v1",
                "matchedVideoTitle": yt_title,
                "matchRule": best["rule"],
                "addedAt": now,
                "appleCollectionId": cid,
                "youtubeChannelId": channel,
                "youtubeDurationSeconds": int(duration),
            }
            selected.append({"trackId": tid, "score": score, "record": record})

    summary = {
        "mode": "PUBBLICAZIONE_AUTOMATICA" if PUBBLICA else "SOLO_SIMULAZIONE",
        "reportGeneratedAt": report["generatedAt"],
        "podcastAnalizzati": len(report["podcasts"]),
        "candidatiFortiNelReport": report["totalStrongCandidates"],
        "candidatiDaVerificareNonPubblicabili": report["totalToReview"],
        "nuoviCollegamentiSelezionati": len(selected),
        "sospesiPerSicurezza": len(held),
        "giaPresentiIdentici": len(skipped),
        "catalogoPrima": len(saved),
        "nuoviCollegamentiEffettivamenteAggiunti": len(selected) if PUBBLICA else 0,
        "catalogoDopo": len(saved) + (len(selected) if PUBBLICA else 0),
        "motiviSospensione": dict(Counter(h["reason"] for h in held)),
        "perPodcast": dict(Counter(s["record"]["podcast"] for s in selected)),
    }
    return {"summary": summary, "selected": selected, "held": held, "existing": skipped}


def atomic_save(path, data):
    fd, tmp = tempfile.mkstemp(prefix="meron-videos-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    report_path = BASE / "altri_podcast_youtube_report.json"
    config_path = BASE / "config_youtube_altri_podcast.json"
    catalog_path = BASE / "videos.json"
    original = catalog_path.read_bytes()  # fail closed: il catalogo reale deve esserci
    old_hash = hashlib.sha256(original).hexdigest()
    catalog = json.loads(original.decode("utf-8-sig"))
    if not isinstance(catalog, dict):
        raise ValueError("Catalogo non valido")
    report, config = load_dict(report_path), load_dict(config_path)
    preview = safe_candidates(report, catalog, config)
    summary = preview["summary"]
    # Gli esiti si salvano in file separati, senza alterare videos.json.
    atomic_save(BASE / "anteprima_video_altri_podcast.json", preview)
    with (BASE / "anteprima_video_altri_podcast.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["podcast", "appleTrackId", "episodioApple", "stato",
                         "score", "youtubeUrl", "titoloYouTube", "motivo"])
        for obj in preview["selected"]:
            r = obj["record"]
            writer.writerow([r["podcast"], obj["trackId"], r["episode"], "SELEZIONATO",
                             obj["score"], r["youtubeUrl"], r["matchedVideoTitle"], r["matchRule"]])
        for obj in preview["held"]:
            writer.writerow([obj.get("podcast"), obj.get("trackId"), obj.get("episode"),
                             "SOSPESO", obj.get("score"), obj.get("youtubeUrl"),
                             obj.get("youtubeTitle"), obj["reason"]])
    if PUBBLICA and preview["selected"]:
        if hashlib.sha256(catalog_path.read_bytes()).hexdigest() != old_hash:
            raise RuntimeError("Catalogo modificato durante la verifica: NON scrivo")
        merged = dict(catalog)
        merged["videos"] = dict(catalog["videos"])
        for item in preview["selected"]:
            tid = item["trackId"]
            if tid in merged["videos"]:
                raise RuntimeError("Conflitto durante l'aggiunta: NON scrivo")
            merged["videos"][tid] = item["record"]
        atomic_save(catalog_path, merged)
    elif not PUBBLICA and hashlib.sha256(catalog_path.read_bytes()).hexdigest() != old_hash:
        raise RuntimeError("videos.json cambiato in simulazione: errore")

    print("MERON - ANTEPRIMA PUBBLICAZIONE VIDEO ALTRI PODCAST")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print("verified: false su tutti i nuovi collegamenti; nessun precedente sovrascritto")
    print("La data di pubblicazione YouTube non e' disponibile nel rapporto: i match non sono verificati manualmente")
    print("Rapporti: anteprima_video_altri_podcast.json e anteprima_video_altri_podcast.csv")
    if not PUBBLICA:
        print("SIMULAZIONE: videos.json INALTERATO; niente commit di pubblicazione")
    else:
        print("ATTENZIONE: videos.json aggiornato localmente; il workflow effettua il push su GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
