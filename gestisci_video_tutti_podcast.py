#!/usr/bin/env python3
"""MerON - coda persistente e pubblicazione prudente video degli altri podcast.

Modalita (variabile MERON_MODALITA):
  SIMULAZIONE: incorpora nel file coda proposte del nuovo lotto, senza toccare videos.json.
  PUBBLICAZIONE: pubblica SOLO le proposte gia in coda, senza lanciare scansioni.

Le proposte entrano da rapporti verificati tramite i filtri del programma esistente.
Si pubblicano automaticamente solo titoli esattamente coincidenti, video unici,
metadati validi e collegamenti non gia presenti. I dubbi restano in coda.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pubblica_video_altri_podcast as filters

BASE = Path(__file__).resolve().parent
QUEUE_PATH = BASE / 'coda_video_tutti_podcast.json'
CATALOG_PATH = BASE / 'videos.json'
REPORT_PATH = BASE / 'rapporto_youtube_batch_tutti_podcast.json'
CONFIG_PATH = BASE / 'config_batch_video_tutti_podcast.json'
PREVIEW_JSON = BASE / 'anteprima_coda_video_tutti_podcast.json'
PREVIEW_CSV = BASE / 'anteprima_coda_video_tutti_podcast.csv'
APPLE_ID = re.compile(r'\d{5,20}\Z')
CHANNEL_ID = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
YOUTUBE_VIDEO = re.compile(r'[A-Za-z0-9_-]{11}\Z')
MAX_ADDITIONS = 200
MIN_PRESERVED = 560


def utc_now():
    return datetime.now(timezone.utc)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path, data):
    fd, tmp = tempfile.mkstemp(prefix='meron-coda-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def normalized_title(text):
    if not isinstance(text, str):
        return ''
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def valid_utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def youtube_id(url):
    return filters.youtube_id(url)


def candidate_key(item):
    return (str(item['trackId']), item['record']['youtubeUrl'])


def validate_item(item, existing_urls, existing_ids, video_counts, track_counts):
    if not isinstance(item, dict) or not isinstance(item.get('record'), dict):
        return 'RECORD_NON_VALIDO'
    r = item['record']
    tid = str(item.get('trackId', ''))
    url = r.get('youtubeUrl')
    vid = youtube_id(url)
    channel = r.get('youtubeChannelId')
    collection = str(r.get('appleCollectionId', ''))
    title = r.get('episode')
    yt_title = r.get('matchedVideoTitle')
    duration = r.get('youtubeDurationSeconds')
    score = item.get('score')
    if (not APPLE_ID.fullmatch(tid) or not APPLE_ID.fullmatch(collection)
            or not isinstance(vid, str) or not YOUTUBE_VIDEO.fullmatch(vid)
            or url != f'https://www.youtube.com/watch?v={vid}'
            or not isinstance(channel, str) or not CHANNEL_ID.fullmatch(channel)):
        return 'ID_NON_VALIDI'
    if (not isinstance(r.get('podcast'), str) or not r['podcast'].strip()
            or not isinstance(title, str) or not title.strip()
            or not isinstance(yt_title, str) or not yt_title.strip()
            or len(title) > 500 or len(yt_title) > 500):
        return 'TITOLI_NON_VALIDI'
    if (r.get('verified') is not False or r.get('automaticMatch') is not True
            or r.get('matchMethod') != 'youtube-altri-podcast-verifica-incrociata-v1'):
        return 'ORIGINE_NON_VALIDA'
    if (not isinstance(score, int) or isinstance(score, bool) or score < 110
            or r.get('matchRule') != 'Titolo identico'
            or normalized_title(title) != normalized_title(yt_title)):
        return 'DA_VERIFICARE_TITOLO'
    if (not isinstance(duration, int) or isinstance(duration, bool)
            or not 600 <= duration <= 86400):
        return 'DURATA_NON_VALIDA'
    timestamp = valid_utc(item.get('sourceGeneratedAt'))
    if timestamp is None:
        return 'DATA_REPORT_NON_VALIDA'
    age_days = (utc_now() - timestamp).total_seconds() / 86400
    if age_days < -1 or age_days > 90:
        return 'REPORT_TROPPO_VECCHIO'
    if track_counts[tid] != 1 or video_counts[vid] != 1:
        return 'CONFLITTO_NELLA_CODA'
    if tid in existing_ids:
        old = existing_ids[tid]
        if isinstance(old, dict) and youtube_id(old.get('youtubeUrl')) == vid:
            return 'GIA_PRESENTE_IDENTICO'
        return 'ID_APPLE_GIA_USATO_DIVERSAMENTE'
    if vid in existing_urls:
        return 'VIDEO_GIA_PRESENTE_IN_CATALOGO'
    return None


def collect_from_latest_report(catalog):
    """Rilegge il rapporto della scansione *appena eseguita*, non una vecchia anteprima."""
    if not REPORT_PATH.exists() and not CONFIG_PATH.exists():
        return [], 0, 0
    if not REPORT_PATH.exists() or not CONFIG_PATH.exists():
        raise ValueError('Report del lotto e configurazione devono esistere insieme')
    report, config = read_json(REPORT_PATH), read_json(CONFIG_PATH)
    if report.get('showsConfigured') == 0 and not config.get('podcasts'):
        if report.get('totalStrongCandidates') or report.get('totalToReview'):
            raise ValueError('Conteggi inattesi per lotto vuoto')
        return [], 0, 0
    # Nel repository il vecchio programma e' impostato su PUBBLICA=True.
    # Eseguiamo SOLO il suo filtro, mai la funzione main() che scrive il catalogo.
    filters.PUBBLICA = False
    data = filters.safe_candidates(report, catalog, config)
    stamp = str(report['generatedAt'])
    items = [dict(row, sourceGeneratedAt=stamp, source='scansione-giornaliera')
             for row in data['selected']]
    return items, len(data['held']), len(data['existing'])


def main():
    mode = os.environ.get('MERON_MODALITA', 'SIMULAZIONE').strip().upper()
    if mode not in ('SIMULAZIONE', 'PUBBLICAZIONE'):
        raise ValueError('MERON_MODALITA non valida: usare SIMULAZIONE o PUBBLICAZIONE')
    original = CATALOG_PATH.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()
    catalog = json.loads(original.decode('utf-8-sig'))
    if not isinstance(catalog, dict) or not isinstance(catalog.get('videos'), dict):
        raise ValueError('videos.json non valido: non modifico nulla')
    saved = catalog['videos']
    if len(saved) < MIN_PRESERVED:
        raise ValueError(f'Catalogo con meno di {MIN_PRESERVED} collegamenti: operazione bloccata')
    if QUEUE_PATH.exists():
        queue = read_json(QUEUE_PATH)
    else:
        queue = {'version': 1, 'pending': []}
    if not isinstance(queue, dict) or queue.get('version') != 1 or not isinstance(queue.get('pending'), list):
        raise ValueError('Coda non valida: nessun aggiornamento')
    pending = queue['pending']
    for item in pending:
        if not isinstance(item, dict) or not isinstance(item.get('record'), dict) or 'trackId' not in item or 'youtubeUrl' not in item['record']:
            raise ValueError('Coda contiene elemento non valido: nessun aggiornamento')
    first_count = len(pending)
    seen = set(candidate_key(x) for x in pending)
    imported = 0
    excluded_at_source = 0
    existing_at_source = 0
    if mode == 'SIMULAZIONE' and os.environ.get('MERON_LEGGI_LOTTO') == '1':
        incoming, excluded_at_source, existing_at_source = collect_from_latest_report(catalog)
        for item in incoming:
            key = candidate_key(item)
            if key not in seen:
                pending.append(item)
                seen.add(key)
                imported += 1

    # I video gia usati nel catalogo restano indisponibili per altri episodi.
    existing_urls = set()
    for r in saved.values():
        if isinstance(r, dict):
            vid = youtube_id(r.get('youtubeUrl'))
            if vid:
                existing_urls.add(vid)
    video_counts = Counter(youtube_id(x['record'].get('youtubeUrl')) for x in pending)
    track_counts = Counter(str(x['trackId']) for x in pending)
    ready, held, linked = [], [], []
    for item in pending:
        why = validate_item(item, existing_urls, saved, video_counts, track_counts)
        if why == 'GIA_PRESENTE_IDENTICO':
            linked.append(item)
        elif why:
            held.append({'trackId': str(item['trackId']), 'episode': item['record'].get('episode'),
                         'podcast': item['record'].get('podcast'), 'reason': why})
        else:
            ready.append(item)

    # Limite prudenziale: pubblicazione manuale massimo 200 alla volta.
    publication = ready[:MAX_ADDITIONS] if mode == 'PUBBLICAZIONE' else []
    publication_ids = {candidate_key(x) for x in publication}
    linked_ids = {candidate_key(x) for x in linked}
    remaining = [x for x in pending if candidate_key(x) not in publication_ids | linked_ids]
    summary = {
        'modalita': mode,
        'nuoveProposteAggiunteAllaCoda': imported,
        'candidatiGiaInCodaPrima': first_count,
        'candidatiTotaliValutati': len(pending),
        'prontiPerPubblicazione': len(ready),
        'sospesiPerSicurezza': len(held),
        'giaPubblicatiIdentici': len(linked),
        'esclusiDalNuovoRapporto': excluded_at_source,
        'giaPresentiNelNuovoRapporto': existing_at_source,
        'nuoviCollegamentiEffettivamenteAggiunti': len(publication),
        'catalogoPrima': len(saved),
        'catalogoDopo': len(saved) + len(publication),
        'inCodaDopo': len(remaining) if mode == 'PUBBLICAZIONE' else len(pending) - len(linked),
        'motiviSospensione': dict(Counter(x['reason'] for x in held)),
    }
    report = {'summary': summary, 'ready': ready, 'held': held,
              'alreadyPublished': linked, 'publishedThisRun': publication}
    if hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest() != original_hash:
        raise RuntimeError('videos.json modificato durante il controllo: nessuna scrittura')
    if publication:
        updated = dict(catalog)
        new_saved = dict(saved)
        for item in publication:
            tid = str(item['trackId'])
            if tid in new_saved:
                raise RuntimeError('Conflitto ID Apple durante il salvataggio')
            new_saved[tid] = item['record']
        updated['videos'] = new_saved
        save_json(CATALOG_PATH, updated)
    queue['pending'] = remaining if mode == 'PUBBLICAZIONE' else [x for x in pending if candidate_key(x) not in linked_ids]
    save_json(QUEUE_PATH, queue)
    save_json(PREVIEW_JSON, report)
    with PREVIEW_CSV.open('w', encoding='utf-8-sig', newline='') as file:
        w = csv.writer(file, delimiter=';')
        w.writerow(['podcast', 'appleTrackId', 'episodio', 'youtubeUrl', 'score', 'stato', 'motivo'])
        for item in ready:
            rec = item['record']
            w.writerow([rec['podcast'], item['trackId'], rec['episode'], rec['youtubeUrl'], item['score'],
                        'PUBBLICATO' if candidate_key(item) in publication_ids else 'PRONTO', rec['matchRule']])
        for item in held:
            w.writerow([item['podcast'], item['trackId'], item['episode'], '', '', 'SOSPESO', item['reason']])
    print('MERON - CODA E PUBBLICAZIONE VIDEO TUTTI I PODCAST')
    for k, v in summary.items():
        print(f'{k}: {v}')
    print('Tutti i nuovi collegamenti: verified=false. Nessuna voce precedente sovrascritta.')
    if mode == 'SIMULAZIONE':
        print('SIMULAZIONE: videos.json INALTERATO. Proposte aggiunte alla coda persistente.')
    else:
        print('PUBBLICAZIONE: videos.json aggiornato in questa esecuzione solo se nuovi > 0.')
        print('Il workflow deve completare il commit e push su GitHub per il salvataggio definitivo.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
