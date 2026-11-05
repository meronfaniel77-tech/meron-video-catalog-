#!/usr/bin/env python3
"""Controllo aggiuntivo: nessuna sovrascrittura, nessun candidato incerto perso."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import gestisci_video_tutti_podcast as manager

BASE = Path(__file__).resolve().parent
SNAPSHOT = BASE / '.meron-guard-snapshot.json'  # escluso dal commit (git add esplicito)
MAX_NEW = 200


def fail(message: str) -> None:
    raise SystemExit('BLOCCO DI SICUREZZA MERON: ' + message)


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        fail(f'impossibile leggere {path.name}: {error}')


def catalog_and_queue():
    catalog = read(BASE / 'videos.json')
    queue = read(BASE / 'coda_video_tutti_podcast.json')
    if not isinstance(catalog, dict) or not isinstance(catalog.get('videos'), dict):
        fail('catalogo non valido')
    if not isinstance(queue, dict) or not isinstance(queue.get('pending'), list):
        fail('coda non valida')
    return catalog, queue


def key(item):
    return (str(item['trackId']), item['record']['youtubeUrl'])


def snapshot():
    cat, queue = catalog_and_queue()
    if len(cat['videos']) < manager.MIN_PRESERVED:
        fail('catalogo iniziale sospettosamente piccolo')
    SNAPSHOT.write_text(json.dumps({'catalog': cat, 'queue': queue}, ensure_ascii=False), encoding='utf-8')
    print(f'MERON PROTEZIONE: snapshot di {len(cat["videos"])} video e {len(queue["pending"])} candidati')


def verify():
    if not SNAPSHOT.exists():
        fail('snapshot iniziale mancante')
    before = read(SNAPSHOT)
    after_catalog, after_queue = catalog_and_queue()
    published_report = read(BASE / 'anteprima_coda_video_tutti_podcast.json')
    original = before['catalog']['videos']
    current = after_catalog['videos']
    old_pending = before['queue']['pending']
    new_pending = after_queue['pending']
    published = published_report.get('publishedThisRun')
    if not isinstance(published, list):
        fail('rapporto pubblicazione assente o invalido')

    for track, original_record in original.items():
        if track not in current or current[track] != original_record:
            fail(f'collegamento preesistente alterato: {track}')
    added_ids = set(current) - set(original)
    if len(added_ids) > MAX_NEW:
        fail(f'troppi nuovi video in una singola esecuzione: {len(added_ids)}')
    if len(published) != len(added_ids):
        fail('numero di collegamenti pubblicati diverso dal rapporto')
    if {str(x['trackId']) for x in published} != added_ids:
        fail('gli ID aggiunti non coincidono con quelli approvati')

    previously_used_ids = {
        manager.youtube_id(record.get('youtubeUrl'))
        for record in original.values() if isinstance(record, dict)
    }
    new_urls = [manager.youtube_id(current[track].get('youtubeUrl')) for track in added_ids]
    if any(not vid or vid in previously_used_ids for vid in new_urls):
        fail('video nuovo gia usato nel catalogo')
    if len(set(new_urls)) != len(new_urls):
        fail('video YouTube ripetuto fra i nuovi collegamenti')

    # La coda deve conservare ogni candidato precedente non pubblicato,
    # tranne eventuali candidati che risultavano gia pubblicati identici.
    published_keys = {key(x) for x in published}
    remaining_keys = {key(x) for x in new_pending}
    for item in old_pending:
        k = key(item)
        if k in published_keys or k in remaining_keys:
            continue
        tid, url = k
        old = original.get(tid)
        if not isinstance(old, dict) or old.get('youtubeUrl') != url:
            fail(f'candidato sospeso scomparso dalla coda: {tid}')

    # Ricalcola gli stessi vincoli rigorosi del gestore, usando la coda
    # ricostruita prima della rimozione dei nuovi video pubblicati.
    entire_queue = [*new_pending, *published]
    video_counts = Counter(manager.youtube_id(x['record'].get('youtubeUrl')) for x in entire_queue)
    track_counts = Counter(str(x['trackId']) for x in entire_queue)
    for item in published:
        reason = manager.validate_item(item, previously_used_ids, original, video_counts, track_counts)
        if reason is not None:
            fail(f'candidato non sicuro pubblicato: {item["trackId"]} ({reason})')
        if current[str(item['trackId'])] != item['record']:
            fail('record pubblicato diverso dalla proposta convalidata')

    print(f'MERON PROTEZIONE OK: conservati {len(original)} video precedenti; '
          f'aggiunti {len(added_ids)} video; rimasti in coda {len(new_pending)} candidati.')
    SNAPSHOT.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'prima', 'dopo'}:
        fail('uso: python verifica_meron_automatica.py prima|dopo')
    snapshot() if sys.argv[1] == 'prima' else verify()
