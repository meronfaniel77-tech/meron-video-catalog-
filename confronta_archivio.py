def numero_parte(titolo):
    m = re.search(r'\b(?:pt|part|parte)\s*([1-9])\b', normalizza(titolo))
    return int(m.group(1)) if m else None


def punteggio_base(titolo, descrizione, titolo_video, frequenze, totale):
    titolo_parole = parole_importanti(titolo)
    video_parole = parole_importanti(titolo_video)
    comuni_titolo = titolo_parole & video_parole
    comuni_descrizione = (parole_importanti(descrizione) & video_parole) - comuni_titolo
    specifiche = comuni_titolo - GENERICHE
    descr_specifiche = comuni_descrizione - GENERICHE
    def peso(p):
        return math.log(1 + totale / (1 + frequenze.get(p, 0)))
    score = sum(peso(p) * (0.35 if p in GENERICHE else 1) for p in comuni_titolo)
    score += min(sum(peso(p) for p in descr_specifiche) * 0.15, 1.5)
    if len(specifiche) >= 2:
        score += 2
    rare = [p for p in specifiche if frequenze.get(p, 0) <= 2]
    if rare:
        score += 1
    return {'score': round(score, 3), 'common': sorted(comuni_titolo | comuni_descrizione),
            'title_matches': len(specifiche), 'description_matches': len(descr_specifiche),
            'rare_matches': len(rare), 'rare_words': sorted(rare)}


def carica_modello():
    try:
        from sentence_transformers import SentenceTransformer
        print('Caricamento controllo bilingue...')
        return SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    except Exception as exc:
        print('Modello bilingue non disponibile; uso il confronto parole:', str(exc)[:160])
        return None


def controlla():
    with FILE_APPLE.open(encoding='utf-8') as f:
        episodi = json.load(f)['episodes']
    with FILE_YOUTUBE.open(encoding='utf-8') as f:
        video = json.load(f)['videos']
    with FILE_CATALOGO.open(encoding='utf-8') as f:
        catalogo = json.load(f)['videos']
    if not isinstance(episodi, list) or not isinstance(video, list) or not isinstance(catalogo, dict):
        raise ValueError('Formato JSON non valido')
    video = [v for v in video if isinstance(v.get('url'), str) and v['url'].startswith('https://www.youtube.com/watch?v=')]
    frequenze = Counter()
    for v in video:
        frequenze.update(parole_importanti(v.get('title', '')))

    # Secondo controllo bilingue: NON sostituisce i risultati del motore precedente.
    modello = carica_modello()
    similarita = None
    if modello is not None and episodi and video:
        import numpy as np
        titoli = [e.get('titolo', '') for e in episodi] + [v.get('title', '') for v in video]
        vettori = modello.encode(titoli, normalize_embeddings=True, show_progress_bar=False)
        similarita = np.asarray(vettori[:len(episodi)]) @ np.asarray(vettori[len(episodi):]).T

    risultati = []
    for i, episodio in enumerate(episodi):
        titolo = episodio.get('titolo', '')
        descrizione = episodio.get('descrizione', '')
        candidati = []
        for j, v in enumerate(video):
            titolo_video = v.get('title', '')
            parte_a, parte_y = numero_parte(titolo), numero_parte(titolo_video)
            if parte_a is not None and parte_y is not None and parte_a != parte_y:
                continue
            analisi = punteggio_base(titolo, descrizione, titolo_video, frequenze, len(video))
            sem = float(similarita[i, j]) if similarita is not None else 0.0
            # Per 'da verificare' basta un indizio lessicale O semantico.
            if not analisi['common'] and sem < 0.40:
                continue
            parte_incerta = (parte_a is None) != (parte_y is None)
            # Lo score originale rimane invariato: non perdiamo i candidati forti precedenti.
            analisi.update({'title': titolo_video, 'url': v['url'],
                            'similarity': round(sem, 3) if similarita is not None else None,
                            'parte_incerta': parte_incerta,
                            'ranking_score': round(analisi['score'] + max(0, sem - 0.40) * 3, 3)})
            candidati.append(analisi)

        # La decisione 'forte' usa gli stessi criteri del codice ripristinato.
        candidati_base = sorted(candidati, key=lambda c: c['score'], reverse=True)
        stato = 'DA_VERIFICARE' if candidati else 'NESSUNA_CORRISPONDENZA'
        migliore = candidati_base[0] if candidati_base else None
        if migliore:
            secondo = candidati_base[1]['score'] if len(candidati_base) > 1 else 0
            forte = (migliore['title_matches'] >= 2 or
                     (migliore['title_matches'] >= 1 and migliore['rare_matches'] >= 1 and migliore['score'] >= 5))
            if (forte and migliore['score'] >= 5 and not migliore['parte_incerta'] and
                    (secondo == 0 or migliore['score'] > secondo * 1.5)):
                stato = 'CANDIDATO_FORTE'
        # Se e' forte, teniamo al primo posto il candidato valutato dal vecchio algoritmo.
        # Negli altri casi mostriamo 5 proposte ordinate usando anche il modello bilingue.
        if stato == 'CANDIDATO_FORTE':
            altri = sorted((c for c in candidati if c is not migliore),
                           key=lambda c: c['ranking_score'], reverse=True)
            migliori = [migliore] + altri[:4]
        else:
            migliori = sorted(candidati, key=lambda c: c['ranking_score'], reverse=True)[:5]
        risultati.append({'trackId': episodio.get('id'), 'episode': titolo,
                          'status': stato, 'candidates': migliori})

    utilizzi = defaultdict(list)
    for r in risultati:
        if r['status'] == 'CANDIDATO_FORTE' and r['candidates']:
            utilizzi[r['candidates'][0]['url']].append(r)
    for gruppo in utilizzi.values():
        if len(gruppo) > 1:
            for r in gruppo:
                r['status'] = 'DA_VERIFICARE'

    forti = sum(r['status'] == 'CANDIDATO_FORTE' for r in risultati)
    senza = sum(r['status'] == 'NESSUNA_CORRISPONDENZA' for r in risultati)
    nuovi = sum(r['status'] == 'CANDIDATO_FORTE' and str(r['trackId']) not in catalogo for r in risultati)
    print('MERON - CONTROLLO COMBINATO')
    print('Episodi Apple:', len(episodi))
    print('Video YouTube:', len(video))
    print('Candidati forti:', forti)
    print('Nuovi candidati forti:', nuovi)
    print('Da verificare:', len(risultati) - forti - senza)
    print('Nessuna corrispondenza:', senza)
    print('Episodi gia nel catalogo:', sum(str(r['trackId']) in catalogo for r in risultati))
    with FILE_RISULTATI.open('w', encoding='utf-8') as f:
        json.dump({'results': risultati}, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('Creato controllo_video_meron.json')
    print('videos.json non modificato')


if __name__ == '__main__':
    controlla()
