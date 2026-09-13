#!/usr/bin/env python3
"""
Refrescar partidos agrupados desde la página móvil de Flashscore (https://m.flashscore.es/).

Estructura real detectada en el HTML de esa página:
  <h4>PAIS: Liga <a ...>Clasificación</a></h4>
  <span>HH:MM</span>Equipo A - Equipo B <a href="/partido/ID/" class="sched">...</a><br />
  ... (más partidos de la misma liga) ...
  <h4>Siguiente PAIS: Liga ...</h4>
  ...

Este script:
  1. Descarga esa página.
  2. Localiza cada bloque <h4>...</h4> y se queda solo con los que coinciden
     exactamente con las ligas solicitadas (ALLOWED_LEAGUES).
  3. Dentro de cada bloque permitido, extrae los partidos (hora, equipos, id).
  4. Intenta obtener cuotas 1/X/2 por partido (mejor esfuerzo).
  5. Agrupa los partidos en bloques de 2 horas, empezando por la hora del
     primer partido del día (p.ej. si el primero es a las 14:00 -> 14-16, 16-18, ...).
  6. Escribe el resultado en partidos_agrupados.txt (y una copia en la carpeta web de XAMPP).
"""
import re
import html as _html
import unicodedata
import requests
from datetime import datetime
import os
import time
from playwright.sync_api import sync_playwright

BASE = 'https://m.flashscore.es/'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

# Ligas exactas solicitadas (tal como aparecen en la página, "PAIS: Liga")
ALLOWED_LEAGUES = [
    'ALEMANIA: Bundesliga',
    'ESPAÑA: LaLiga EA Sports',
    'ESPAÑA: LaLiga Hypermotion',
    'FRANCIA: Ligue 1',
    'ITALIA: Serie A',
    'PORTUGAL: Liga Portugal',
    'INGLATERRA: Premier League',
    'PAÍSES BAJOS: Eredivisie',
]


def _strip_tags(text):
    return re.sub(r'<[^>]+>', '', text or '')


def _norm(s):
    """Normaliza texto: sin acentos, espacios colapsados, minúsculas."""
    if not s:
        return ''
    s2 = unicodedata.normalize('NFKD', s)
    s2 = ''.join(ch for ch in s2 if not unicodedata.combining(ch))
    s2 = re.sub(r'\s+', ' ', s2).strip().lower()
    return s2


def fetch_mobile():
    h = {'User-Agent': USER_AGENT, 'Accept-Language': 'es-ES,es;q=0.9'}
    try:
        r = requests.get(BASE, headers=h, timeout=15)
    except requests.exceptions.SSLError:
        # Algunos equipos Windows no reconocen la cadena de m.flashscore.es.
        # Solo se usa como respaldo para descargar el listado público del día.
        requests.packages.urllib3.disable_warnings()
        r = requests.get(BASE, headers=h, timeout=15, verify=False)
    r.raise_for_status()
    return r.text


def extract_matches(html):
    """Extrae partidos de las ligas permitidas a partir del HTML de m.flashscore.es."""
    html_text = _html.unescape(html)
    allowed_norm = set(_norm(x) for x in ALLOWED_LEAGUES)

    # localizar todos los bloques <h4>...</h4>
    header_matches = list(re.finditer(r'<h4[^>]*>(.*?)</h4>', html_text, flags=re.I | re.S))
    matches = []
    seen_ids = set()

    for i, h in enumerate(header_matches):
        # el h4 contiene "PAIS: Liga <a ...>Clasificación</a>"; nos quedamos solo
        # con el texto antes del primer tag para no arrastrar "Clasificación"
        header_raw = h.group(1).split('<', 1)[0]
        header_raw = re.sub(r'\s+', ' ', header_raw).strip()
        if _norm(header_raw) not in allowed_norm:
            continue

        start = h.end()
        end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(html_text)
        block = html_text[start:end]

        # cada partido: <span>HH:MM</span>Equipo A - Equipo B <a href="/partido/ID/"
        for mm in re.finditer(
            r'<span>(\d{1,2}:\d{2})</span>\s*([^<]+?)\s*<a href="/partido/([A-Za-z0-9]+)/"',
            block, flags=re.I
        ):
            tm = mm.group(1).strip()
            teams_text = mm.group(2).strip()
            mid = mm.group(3).strip()

            if ' - ' not in teams_text:
                continue
            home, away = teams_text.split(' - ', 1)
            home = home.strip()
            away = away.strip()
            if not home or not away:
                continue
            if mid in seen_ids:
                continue
            seen_ids.add(mid)

            matches.append({
                'time': tm,
                'match': f'{home} - {away}',
                'id': mid,
                'league': header_raw.split(':', 1)[1].strip() if ':' in header_raw else header_raw,
                'header_full': header_raw,
            })

    return matches


def fetch_odds_from_flashscore(matches):
    """Obtiene la primera terna 1/X/2 de la pestaña Cuotas de cada partido."""
    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1200}, locale='es-ES')
        age_confirmed = False
        try:
            for match in matches:
                match_id = match.get('id')
                if not match_id:
                    continue
                try:
                    page.goto(f'https://www.flashscore.es/partido/{match_id}/#/resumen-del-partido/', wait_until='domcontentloaded', timeout=45000)
                    if not age_confirmed:
                        for selector in ('#onetrust-accept-btn-handler', 'button:has-text("Aceptar")'):
                            try:
                                page.locator(selector).click(timeout=2000)
                                break
                            except Exception:
                                pass
                        try:
                            page.get_by_text(re.compile('SOY MAYOR DE 18', re.I)).click(timeout=7000)
                            age_confirmed = True
                        except Exception:
                            pass
                    page.get_by_text(re.compile('^CUOTAS$', re.I)).first.click(timeout=12000)
                    page.wait_for_timeout(1200)
                    section = page.locator('body').inner_text(timeout=10000).split('CASA DE APUESTAS', 1)
                    if len(section) != 2:
                        continue
                    # Solo valores decimales: así se excluye la cabecera "1 X 2".
                    values = re.findall(r'\b([1-9]\d?[.,]\d{1,2})\b', section[1])
                    if len(values) >= 3:
                        result[match_id] = tuple(float(value.replace(',', '.')) for value in values[:3])
                except Exception as error:
                    print(f'AVISO: cuotas no disponibles para {match_id}: {error}')
        finally:
            browser.close()
    return result


def group_in_blocks(matches):
    """Agrupa partidos en bloques de 2 horas empezando por la hora del primer partido."""
    horas = []
    for m in matches:
        tm = m.get('time')
        if tm:
            try:
                horas.append(int(tm.split(':')[0]))
            except Exception:
                pass

    blocks = {}
    if not horas:
        blocks['Sin hora - Hoy'] = list(matches)
        return blocks

    min_h = min(horas)
    max_h = max(horas)
    block_starts = list(range(min_h, max_h + 1, 2))

    for s in block_starts:
        blocks[f'Bloque: {s:02d}:00 - {s + 2:02d}:00'] = []

    for m in matches:
        tm = m.get('time')
        assigned = False
        if tm:
            try:
                hh = int(tm.split(':')[0])
            except Exception:
                hh = None
            if hh is not None:
                for s in block_starts:
                    if s <= hh < s + 2:
                        blocks[f'Bloque: {s:02d}:00 - {s + 2:02d}:00'].append(m)
                        assigned = True
                        break
        if not assigned:
            blocks.setdefault('Sin hora - Hoy', []).append(m)

    return blocks


def write_partidos(matches, outpath):
    odds_by_id = fetch_odds_from_flashscore(matches)
    # obtener cuotas (mejor esfuerzo, con pequeña pausa entre peticiones)
    for m in matches:
        time.sleep(0.12)
        odds = odds_by_id.get(m.get('id'))
        if odds:
            m['odds'] = {'1': float(odds[0]), 'X': float(odds[1]), '2': float(odds[2])}
        else:
            m['odds'] = {'1': 0.0, 'X': 0.0, '2': 0.0}

    blocks = group_in_blocks(matches)

    def time_key(mm):
        t = mm.get('time') or ''
        try:
            hh, mi = map(int, t.split(':'))
            return hh * 60 + mi
        except Exception:
            return 9999

    # ordenar los bloques por su hora de inicio, no alfabéticamente
    def block_start_key(label):
        mm = re.search(r'(\d{1,2}):00', label)
        return int(mm.group(1)) if mm else 9999

    lines = []
    lines.append('Partidos agrupados por refresco automático')
    lines.append('Fecha: ' + datetime.now().strftime('%Y-%m-%d %H:%M'))
    lines.append('')
    if not matches:
        lines.append('No se han encontrado partidos de las ligas indicadas en la página móvil.')
    else:
        for blk in sorted(blocks.keys(), key=block_start_key):
            lines.append('')
            lines.append(blk)
            for m in sorted(blocks[blk], key=time_key):
                o = m.get('odds', {})
                odds_str = ''
                if o and o.get('1'):
                    odds_str = f" (odds: {o.get('1'):.2f}/{o.get('X'):.2f}/{o.get('2'):.2f})"
                lines.append(f"- [{m.get('league')}] {m.get('time')} {m.get('match')}   (id: {m.get('id')}){odds_str}")

    content = '\n'.join(lines)
    with open(outpath, 'w', encoding='utf-8') as f:
        f.write(content)

    # copia en la carpeta web para que Apache la lea directamente
    try:
        web_out = r'C:/xampp/htdocs/ProyectoBetPredictor/partidos_agrupados.txt'
        with open(web_out, 'w', encoding='utf-8') as f2:
            f2.write(content)
    except Exception:
        pass


def main():
    out = os.path.join(os.path.dirname(__file__), 'partidos_agrupados.txt')
    try:
        html = fetch_mobile()
    except Exception as e:
        print('ERROR: No se pudo descargar la página móvil de Flashscore:', e)
        return
    matches = extract_matches(html)
    write_partidos(matches, out)
    print(f'Generado {out} (partidos de ligas solicitadas: {len(matches)})')


if __name__ == '__main__':
    main()
