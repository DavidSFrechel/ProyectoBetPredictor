import os
import re
import time
import unicodedata
from datetime import datetime
import sys

import requests

BASE_URL = "https://m.flashscore.es"
HOME_URL = f"{BASE_URL}/"
H2H_URL_TEMPLATE = f"{BASE_URL}/partido/{{match_id}}/?t=h2h"
STATS_URL_TEMPLATE = f"{BASE_URL}/partido/{{match_id}}/?t=estadisticas"

# Puedes poner un alias conocido ("la_liga", "premier_league", etc.)
# o una URL completa de FootyStats con la tabla de clasificacion.

LIGA_URLS = {
    "la_liga": "https://footystats.org/es/spain/la-liga",
    "laliga_ea_sports": "https://footystats.org/es/spain/la-liga",
    "laliga_hypermotion": "https://footystats.org/es/spain/la-liga-hypermotion",
    "premier_league": "https://footystats.org/es/england/premier-league",
    "championship": "https://footystats.org/es/england/championship",
    "serie_a": "https://footystats.org/es/italy/serie-a",
    "bundesliga": "https://footystats.org/es/germany/bundesliga",
    "ligue_1": "https://footystats.org/es/france/ligue-1",
    "liga_portugal": "https://footystats.org/es/portugal/liga-portugal",
    "eredivisie": "https://footystats.org/es/netherlands/eredivisie",
}

LIGA_ALIASES = {
    "la_liga": "la_liga",
    "laliga": "la_liga",
    "laliga_ea_sports": "la_liga",
    "laliga_hypermotion": "laliga_hypermotion",
    "la_liga_hypermotion": "laliga_hypermotion",
    "laliga_smartbank": "laliga_hypermotion",
    "premier_league": "premier_league",
    "premier": "premier_league",
    "championship": "championship",
    "serie_a": "serie_a",
    "bundesliga": "bundesliga",
    "ligue_1": "ligue_1",
    "ligue1": "ligue_1",
    "liga_portugal": "liga_portugal",
    "liga_portugal_bwin": "liga_portugal",
    "eredivisie": "eredivisie",
}

LOCAL_TEAM = "Real Sociedad"
VISITOR_TEAM = "Atlético de Madrid"
LIGA = "serie_a"  # o URL completa de la liga en footystats

# Permitir sobrescribir variables desde argumentos de línea de comandos:
# Uso: python estadisticas_ultimos_cinco_mobile.py "liga_or_match" "match_if_needed"
def _override_from_argv():
    global LOCAL_TEAM, VISITOR_TEAM, LIGA
    try:
        # Recolectar argumentos posicionales ignorando flags que empiezan por '-'
        pos_args = [a for a in sys.argv[1:] if not a.startswith('-')]
        if len(pos_args) >= 1:
            arg1 = pos_args[0].strip()
            if arg1:
                key = arg1.lower().replace(' ', '_')
                alias_key = LIGA_ALIASES.get(key, key)
                if arg1.startswith('http') or alias_key in LIGA_URLS:
                    LIGA = arg1
                elif ' - ' in arg1 or '-' in arg1:
                    sep = ' - ' if ' - ' in arg1 else '-'
                    parts = [p.strip() for p in arg1.split(sep, 1)]
                    if len(parts) == 2:
                        LOCAL_TEAM, VISITOR_TEAM = parts[0], parts[1]
        if len(pos_args) >= 2:
            arg2 = pos_args[1].strip()
            if arg2:
                if ' - ' in arg2 or '-' in arg2:
                    sep = ' - ' if ' - ' in arg2 else '-'
                    parts = [p.strip() for p in arg2.split(sep, 1)]
                    if len(parts) == 2:
                        LOCAL_TEAM, VISITOR_TEAM = parts[0], parts[1]
                else:
                    key = arg2.lower().replace(' ', '_')
                    alias_key = LIGA_ALIASES.get(key, key)
                    if arg2.startswith('http') or alias_key in LIGA_URLS:
                        LIGA = arg2
    except Exception:
        pass

_override_from_argv()
MAX_PARTIDOS = 5

HTTP_TIMEOUT = 12
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

STAT_LABELS = {
    "shots_total": {"Remates totales", "Tiros totales", "Remates", "Tiros", "Total shots", "Shots total", "Shots"},
    "shots_on_target": {"Remates a puerta", "Tiros a puerta", "Shots on target", "Shots on goal"},
    "corners": {"Córneres", "Córners", "Saques de esquina", "Corneres", "Corners", "Corner kicks"},
    "yellow_cards": {"Tarjetas amarillas", "Yellow cards"},
}
NUM_RE = re.compile(r"\d+")
SCORE_RE = re.compile(r"(\d+)\s*[:\-]\s*(\d+)")


def _strip_html_tags(texto: str) -> str:
    if not texto:
        return ""
    limpio = re.sub(r"<[^>]+>", " ", texto)
    return " ".join(limpio.split())


def _normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    return texto


def _coincide_equipo(nombre_dom: str, nombre_usuario: str) -> bool:
    dom_norm = _normalizar_texto(nombre_dom)
    usr_norm = _normalizar_texto(nombre_usuario)
    if not dom_norm or not usr_norm:
        return False
    if dom_norm == usr_norm:
        return True
    return (
        dom_norm.startswith(usr_norm)
        or usr_norm.startswith(dom_norm)
        or dom_norm in usr_norm
        or usr_norm in dom_norm
    )


def _etiqueta_coincide(etiqueta: str, posibles: set) -> bool:
    t = _normalizar_texto(etiqueta)
    if not t:
        return False
    for p in posibles:
        p_norm = _normalizar_texto(p)
        if p_norm == t or p_norm in t or t in p_norm:
            return True
    return False


def _get_session() -> requests.Session:
    sess = requests.Session()
    # En este equipo Python no reconoce la cadena TLS de m.flashscore.es.
    # La sesión se limita a las fuentes públicas usadas por este script.
    requests.packages.urllib3.disable_warnings()
    sess.verify = False
    sess.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return sess


def _parse_int(texto: str):
    if texto is None:
        return None
    texto = texto.replace("+", "").strip()
    m = NUM_RE.search(texto)
    return int(m.group(0)) if m else None


def _parse_float(texto: str):
    if texto is None:
        return None
    texto = texto.strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", texto)
    return float(m.group(0)) if m else None


def _parse_pct(texto: str):
    valor = _parse_float(texto)
    return (valor / 100.0) if valor is not None else None


def _resolver_liga_url(liga):
    if not liga:
        return None
    liga = liga.strip()
    if not liga:
        return None
    if liga.startswith(("http://", "https://")):
        return liga
    key = _normalizar_texto(liga).replace(" ", "_")
    alias_key = LIGA_ALIASES.get(key, key)
    return LIGA_URLS.get(alias_key)


def _extraer_tabla_footystats(html_text: str):
    m = re.search(
        r"<table class='full-league-table table-sort col-sm-12 mobify-table' data-table-page='1'>(.*?)</table>",
        html_text,
        flags=re.S,
    )
    if not m:
        return {}

    tabla = m.group(1)
    equipos = {}
    for row_html in re.findall(r"<tr class='[^']*'>(.*?)</tr>", tabla, flags=re.S):
        cells = re.findall(r"<td class='([^']+)'[^>]*>(.*?)</td>", row_html, flags=re.S)
        if len(cells) < 21:
            continue

        valores = [(_strip_html_tags(c[1]) or "").strip() for c in cells]
        team_name = valores[2]
        if not team_name:
            continue

        forma = "".join(re.findall(r"<li class='form-run [^']+'>([^<]+)</li>", cells[11][1], flags=re.S)).strip()
        mp = _parse_int(valores[3])
        gf = _parse_int(valores[7])
        ga = _parse_int(valores[8])

        equipos[_normalizar_texto(team_name)] = {
            "team": team_name,
            "rank": _parse_int(valores[0]),
            "zone": cells[0][0],
            "mp": mp,
            "wins": _parse_int(valores[4]),
            "draws": _parse_int(valores[5]),
            "losses": _parse_int(valores[6]),
            "gf": gf,
            "ga": ga,
            "gd": _parse_int(valores[9]),
            "points": _parse_int(valores[10]),
            "form": forma,
            "ppg": _parse_float(valores[12]),
            "clean_sheet_pct": _parse_pct(valores[13]),
            "btts_pct": _parse_pct(valores[14]),
            "failed_to_score_pct": _parse_pct(valores[15]),
            "over15_pct": _parse_pct(valores[18]),
            "over25_pct": _parse_pct(valores[19]),
            "avg_goals": _parse_float(valores[20]),
            "gf_pg": _safe_div(gf, mp),
            "ga_pg": _safe_div(ga, mp),
        }
    return equipos


def _buscar_equipo_footystats(tabla: dict, nombre_equipo: str):
    nombre_norm = _normalizar_texto(nombre_equipo)
    if nombre_norm in tabla:
        return tabla[nombre_norm]
    for clave, datos in tabla.items():
        if _coincide_equipo(clave, nombre_norm) or _coincide_equipo(nombre_norm, clave):
            return datos
    return None


def obtener_contexto_footystats(session: requests.Session, league_url: str, local: str, visitante: str):
    if not league_url:
        return None
    try:
        resp = session.get(league_url, timeout=HTTP_TIMEOUT)
    except Exception:
        return None
    if resp.status_code != 200:
        return None

    tabla = _extraer_tabla_footystats(resp.text)
    if not tabla:
        return None

    return {
        "url": league_url,
        "total_equipos": len(tabla),
        "local": _buscar_equipo_footystats(tabla, local),
        "visitante": _buscar_equipo_footystats(tabla, visitante),
    }


def _buscar_partido_id(html_text: str, local: str, visitante: str):
    local_norm = _normalizar_texto(local)
    visit_norm = _normalizar_texto(visitante)
    # Buscar el bloque "Local - Visitante <a href="/partido/ID/" ...>"
    patron = re.compile(
        r"([A-Za-zÀ-ÿ0-9\.\s'-]+)\s*-\s*([A-Za-zÀ-ÿ0-9\.\s'-]+)\s*<a href=\"/partido/([A-Za-z0-9]+)/\"",
        flags=re.I,
    )
    for m in patron.finditer(html_text):
        home = _normalizar_texto(m.group(1))
        away = _normalizar_texto(m.group(2))
        if home == local_norm and away == visit_norm:
            return m.group(3)

    # Fallback: buscar por cercania si hay variaciones de nombre
    for m in re.finditer(r'href="/partido/([A-Za-z0-9]+)/"', html_text):
        match_id = m.group(1)
        idx = m.start()
        ventana = html_text[max(0, idx - 400) : idx + 400]
        texto = _normalizar_texto(_strip_html_tags(ventana))
        if local_norm in texto and visit_norm in texto:
            return match_id
    return None


def _extraer_enlaces_h2h(html_text: str, equipo: str, max_partidos: int):
    block_pattern = re.compile(
        r"<h4[^>]*>(.*?)</h4>.*?<table[^>]*class=['\"]h2h['\"][^>]*>(.*?)</table>",
        flags=re.S | re.I,
    )
    link_pattern = re.compile(
        r"""href=['"](?:https?://(?:www\.)?flashscore\.(?:es|com))?/partido/([A-Za-z0-9]+)/?['"]""",
        flags=re.I,
    )
    equipo_norm = _normalizar_texto(equipo)
    for m in block_pattern.finditer(html_text):
        header = _normalizar_texto(_strip_html_tags(m.group(1)))
        if "ultimos partidos" not in header:
            continue
        if equipo_norm not in header:
            continue
        tabla = m.group(2)
        ids = []
        for href in link_pattern.findall(tabla):
            if href not in ids:
                ids.append(href)
            if len(ids) >= max_partidos:
                break
        return ids
    return []


def _extraer_enlaces_enfrentamientos(html_text: str, max_partidos: int):
    """Extrae los IDs de partido del bloque 'Enfrentamientos' de la página H2H."""
    block_pattern = re.compile(
        r"<h4[^>]*>(.*?)</h4>.*?<table[^>]*class=['\"]h2h['\"][^>]*>(.*?)</table>",
        flags=re.S | re.I,
    )
    link_pattern = re.compile(
        r"""href=['"](?:https?://(?:www\.)?flashscore\.(?:es|com))?/partido/([A-Za-z0-9]+)/?['"]""",
        flags=re.I,
    )
    for m in block_pattern.finditer(html_text):
        header = _normalizar_texto(_strip_html_tags(m.group(1)))
        if not any(token in header for token in ("enfrentamiento", "head to head", "h2h")):
            continue
        tabla = m.group(2)
        ids = []
        for href in link_pattern.findall(tabla):
            if href not in ids:
                ids.append(href)
            if len(ids) >= max_partidos:
                break
        return ids
    return []


def _extraer_equipos_y_marcador_html(html_text: str):
    h3 = re.search(r"<h3>(.*?)</h3>", html_text, flags=re.S)
    if not h3:
        return None, None, None
    texto = _strip_html_tags(h3.group(1))
    partes = [p.strip() for p in texto.split(" - ") if p.strip()]
    if len(partes) < 2:
        return None, None, None
    local, visitante = partes[0], partes[1]

    marcador = None
    m = re.search(r"<div class=\"detail\"><b>(\d+\s*[:\-]\s*\d+)</b>", html_text, flags=re.S)
    if m:
        ms = SCORE_RE.search(m.group(1))
        if ms:
            marcador = (int(ms.group(1)), int(ms.group(2)))
    return local, visitante, marcador


def _extraer_stats_desde_html(html_text: str):
    stats = {}
    row_pattern = re.compile(
        r'data-testid="wcl-statistics".*?'
        r'wcl-homeValue[^>]*>\s*<span[^>]*>(.*?)</span>.*?'
        r'wcl-statistics-category[^>]*>\s*<span[^>]*>(.*?)</span>.*?'
        r'wcl-awayValue[^>]*>\s*<span[^>]*>(.*?)</span>',
        flags=re.S,
    )
    for m in row_pattern.finditer(html_text):
        home_raw, label_raw, away_raw = m.group(1), m.group(2), m.group(3)
        home_nums = NUM_RE.findall(home_raw)
        away_nums = NUM_RE.findall(away_raw)
        if not home_nums or not away_nums:
            continue
        home_val = int(home_nums[0])
        away_val = int(away_nums[0])
        label = _strip_html_tags(label_raw)
        for clave, posibles in STAT_LABELS.items():
            if clave in stats:
                continue
            if _etiqueta_coincide(label, posibles):
                stats[clave] = (home_val, away_val)
                break
    # Fallback: la estructura puede haber cambiado. Buscar etiquetas conocidas
    # y tomar los números más próximos (por ejemplo: "Remates totales" -> 12 6)
    if not stats:
        # Construir un patrón alternativo con las etiquetas posibles
        for clave, posibles in STAT_LABELS.items():
            # crear alternation regex con palabras clave simples
            for posible in posibles:
                if not posible:
                    continue
                # busco todas las apariciones del texto de la etiqueta
                for m in re.finditer(re.escape(posible), html_text, flags=re.I):
                    start = max(0, m.start() - 300)
                    end = min(len(html_text), m.end() + 300)
                    ventana = html_text[start:end]
                    # buscar porcentajes primero (p. ej. 55%) o números
                    nums = re.findall(r"-?\d+(?:[,\.]\d+)?%?", _strip_html_tags(ventana))
                    # limpiar y convertir
                    tokens = []
                    for n in nums:
                        orig = n.strip()
                        n_clean = orig.replace(',', '.').strip()
                        is_pct = n_clean.endswith('%')
                        val = None
                        try:
                            if is_pct:
                                val = float(n_clean[:-1])
                            elif '.' in n_clean:
                                val = float(n_clean)
                            else:
                                val = int(n_clean)
                        except Exception:
                            continue
                        tokens.append((orig, val, is_pct))

                    # Filtrar candidatos plausibles según la estadística buscada
                    def candidatos_enteros(tokens_list, max_val=40):
                        res = []
                        for orig, val, is_pct in tokens_list:
                            if is_pct:
                                continue
                            # preferir enteros
                            if isinstance(val, float) and not val.is_integer():
                                continue
                            try:
                                vi = int(val)
                            except Exception:
                                continue
                            if 0 <= vi <= max_val:
                                res.append(vi)
                        return res

                    # límites por tipo de estadística
                    limites = {"shots_total": 40, "shots_on_target": 25, "corners": 30, "yellow_cards": 10}
                    max_allowed = limites.get(clave, 40)
                    clean_nums = candidatos_enteros(tokens, max_allowed)

                    # si no hay suficientes candidatos enteros, usar los dos primeros números sin porcentajes
                    if len(clean_nums) < 2:
                        clean_nums = [int(t[1]) if isinstance(t[1], (int, float)) and float(t[1]).is_integer() else None for t in tokens if not t[2]]
                        clean_nums = [c for c in clean_nums if c is not None]

                    # necesitamos al menos 2 valores (local, visitante)
                    if len(clean_nums) >= 2:
                        # escoger primer y segundo como home/away
                        home_val = clean_nums[0]
                        away_val = clean_nums[1]
                        # normalizar a int cuando corresponda
                        try:
                            if isinstance(home_val, float) and home_val.is_integer():
                                home_val = int(home_val)
                        except Exception:
                            pass
                        try:
                            if isinstance(away_val, float) and away_val.is_integer():
                                away_val = int(away_val)
                        except Exception:
                            pass
                        # asignar solo si la etiqueta coincide razonablemente
                        if clave not in stats:
                            stats[clave] = (home_val, away_val)
                            break
                if clave in stats:
                    break
    return stats


def extraer_estadisticas_partido(session: requests.Session, match_id: str, equipo_referencia: str):
    url = STATS_URL_TEMPLATE.format(match_id=match_id)
    try:
        resp = session.get(url, timeout=HTTP_TIMEOUT)
    except Exception:
        return None
    if resp.status_code != 200:
        return None

    html_text = resp.text
    local, visitante, marcador = _extraer_equipos_y_marcador_html(html_text)
    stats_brutas = _extraer_stats_desde_html(html_text)

    if not local or not visitante:
        return None

    es_local = _coincide_equipo(local, equipo_referencia)
    if not es_local and _coincide_equipo(visitante, equipo_referencia):
        es_local = False
    if es_local is None:
        es_local = True

    if marcador:
        goles_local, goles_visitante = marcador
    else:
        goles_local = goles_visitante = None

    if es_local:
        equipo = local
        rival = visitante
        goles_equipo = goles_local
        goles_rival = goles_visitante
    else:
        equipo = visitante
        rival = local
        goles_equipo = goles_visitante
        goles_rival = goles_local

    def tomar(clave):
        if clave not in stats_brutas:
            return None, None
        home_val, away_val = stats_brutas[clave]
        if es_local:
            return home_val, away_val
        return away_val, home_val

    remates_favor, remates_contra = tomar("shots_total")
    remates_puerta_favor, remates_puerta_contra = tomar("shots_on_target")
    corners_favor, corners_contra = tomar("corners")
    amarillas_favor, amarillas_contra = tomar("yellow_cards")

    return {
        "equipo": equipo,
        "rival": rival,
        "local": local,
        "visitante": visitante,
        "goles_equipo": goles_equipo,
        "goles_rival": goles_rival,
        "goles_local": goles_local,
        "goles_visitante": goles_visitante,
        "remates_favor": remates_favor,
        "remates_contra": remates_contra,
        "remates_puerta_favor": remates_puerta_favor,
        "remates_puerta_contra": remates_puerta_contra,
        "corners_favor": corners_favor,
        "corners_contra": corners_contra,
        "amarillas_favor": amarillas_favor,
        "amarillas_contra": amarillas_contra,
        "url": url,
    }


def _formato_valor(v):
    return str(v) if v is not None else "-"


def _formato_decimal(v):
    return f"{v:.2f}" if v is not None else "-"


def _safe_div(num, den):
    if den in (None, 0):
        return None
    return num / den


def _puntos_forma(forma: str):
    if not forma:
        return None
    mapa = {"V": 3, "E": 1, "D": 0, "W": 3, "L": 0}
    puntos = 0
    partidos = 0
    for ch in forma:
        valor = mapa.get(ch.upper())
        if valor is None:
            continue
        puntos += valor
        partidos += 1
    return puntos if partidos else None


def generar_informe_txt(
    local,
    visitante,
    estadisticas_local,
    estadisticas_visitante,
    estadisticas_enfrentamientos=None,
    carpeta=None,
    contexto_liga=None,
):
    if carpeta is None:
        carpeta = os.path.dirname(os.path.abspath(__file__))
    seguro = re.sub(r'[<>:"/\\|?*]', "_", f"{local}_vs_{visitante}")
    nombre = f"informe_estadisticas_mobile_{seguro}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    ruta = os.path.join(carpeta, nombre)

    lineas = []
    lineas.append("=" * 70)
    lineas.append("  INFORME ESTADISTICAS - ULTIMOS PARTIDOS")
    lineas.append(f"  Partido principal: {local}  vs  {visitante}")
    lineas.append(f"  Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lineas.append("=" * 70)

    total_equipos_liga = (contexto_liga or {}).get("total_equipos") if contexto_liga else None

    def _resumen_superioridad(lista_est, equipo_ref):
        resumen = {
            "remates": 0,
            "remates_puerta": 0,
            "corners": 0,
            "amarillas": 0,
            "total": 0,
            "local_total": 0,
            "visit_total": 0,
            "local": {"remates": 0, "remates_puerta": 0, "corners": 0, "amarillas": 0},
            "visit": {"remates": 0, "remates_puerta": 0, "corners": 0, "amarillas": 0},
        }
        for est in lista_est or []:
            if not est:
                continue
            es_local = _coincide_equipo(est.get("local", ""), equipo_ref)
            resumen["total"] += 1
            if es_local:
                resumen["local_total"] += 1
            else:
                resumen["visit_total"] += 1

            rf = est.get("remates_favor")
            rc = est.get("remates_contra")
            if rf is not None and rc is not None and rf > rc:
                resumen["remates"] += 1
                if es_local:
                    resumen["local"]["remates"] += 1
                else:
                    resumen["visit"]["remates"] += 1

            rpf = est.get("remates_puerta_favor")
            rpc = est.get("remates_puerta_contra")
            if rpf is not None and rpc is not None and rpf > rpc:
                resumen["remates_puerta"] += 1
                if es_local:
                    resumen["local"]["remates_puerta"] += 1
                else:
                    resumen["visit"]["remates_puerta"] += 1

            cf = est.get("corners_favor")
            cc = est.get("corners_contra")
            if cf is not None and cc is not None and cf > cc:
                resumen["corners"] += 1
                if es_local:
                    resumen["local"]["corners"] += 1
                else:
                    resumen["visit"]["corners"] += 1

            af = est.get("amarillas_favor")
            ac = est.get("amarillas_contra")
            if af is not None and ac is not None and af > ac:
                resumen["amarillas"] += 1
                if es_local:
                    resumen["local"]["amarillas"] += 1
                else:
                    resumen["visit"]["amarillas"] += 1
        return resumen

    def _resumen_metricas(lista_est):
        campos = {
            "remates": "remates_favor",
            "remates_contra": "remates_contra",
            "remates_puerta": "remates_puerta_favor",
            "remates_puerta_contra": "remates_puerta_contra",
            "corners": "corners_favor",
            "corners_contra": "corners_contra",
            "amarillas": "amarillas_favor",
            "amarillas_contra": "amarillas_contra",
        }
        resumen = {}
        for clave, campo in campos.items():
            valores = [est.get(campo) for est in (lista_est or []) if est and est.get(campo) is not None]
            resumen[clave] = {
                "total": sum(valores),
                "partidos": len(valores),
                "media": (sum(valores) / len(valores)) if valores else None,
                "max": max(valores) if valores else None,
                "min": min(valores) if valores else None,
            }
        return resumen

    def _linea_metrica(nombre, favor, contra):
        return (
            f"    {nombre}: favor media {_formato_decimal(favor['media'])} | max {_formato_valor(favor['max'])} | min {_formato_valor(favor['min'])}"
            f" || contra media {_formato_decimal(contra['media'])} | max {_formato_valor(contra['max'])} | min {_formato_valor(contra['min'])}"
        )

    def _media(valores):
        return (sum(valores) / len(valores)) if valores else None

    def _rango(valores):
        return (max(valores) - min(valores)) if valores else None

    def _resumen_avanzado(lista_est):
        rem_f = []
        rem_c = []
        rp_f = []
        rp_c = []
        cor_f = []
        cor_c = []
        am_f = []
        am_c = []
        gol_f = []
        gol_c = []
        net_rem = []
        net_rp = []
        net_cor = []
        intensidad = []
        agresividad = []
        over15 = 0
        btts = 0

        for est in lista_est or []:
            if not est:
                continue

            rf = est.get("remates_favor")
            rc = est.get("remates_contra")
            rpf = est.get("remates_puerta_favor")
            rpc = est.get("remates_puerta_contra")
            cf = est.get("corners_favor")
            cc = est.get("corners_contra")
            af = est.get("amarillas_favor")
            ac = est.get("amarillas_contra")
            gf = est.get("goles_equipo")
            gc = est.get("goles_rival")

            if rf is not None:
                rem_f.append(rf)
            if rc is not None:
                rem_c.append(rc)
            if rpf is not None:
                rp_f.append(rpf)
            if rpc is not None:
                rp_c.append(rpc)
            if cf is not None:
                cor_f.append(cf)
            if cc is not None:
                cor_c.append(cc)
            if af is not None:
                am_f.append(af)
            if ac is not None:
                am_c.append(ac)
            if gf is not None:
                gol_f.append(gf)
            if gc is not None:
                gol_c.append(gc)

            if rf is not None and rc is not None:
                net_rem.append(rf - rc)
            if rpf is not None and rpc is not None:
                net_rp.append(rpf - rpc)
            if cf is not None and cc is not None:
                net_cor.append(cf - cc)
            if rf is not None and rc is not None and cf is not None and cc is not None:
                intensidad.append(rf + rc + cf + cc)
            if af is not None and ac is not None:
                agresividad.append(af + ac)
            if gf is not None and gc is not None:
                if gf + gc >= 2:
                    over15 += 1
                if gf > 0 and gc > 0:
                    btts += 1

        partidos_marcador = min(len(gol_f), len(gol_c))
        n_rem = len(net_rem)
        pesos = list(range(n_rem, 0, -1))
        tendencia_dominio = _safe_div(sum(v * w for v, w in zip(net_rem, pesos)), sum(pesos)) if n_rem else None

        dom_rem = _media(net_rem)
        dom_rp = _media(net_rp)
        dom_cor = _media(net_cor)
        indice_dominio = None
        if dom_rem is not None and dom_rp is not None and dom_cor is not None:
            indice_dominio = 0.45 * dom_rem + 0.35 * dom_rp + 0.20 * dom_cor

        volatilidad = None
        rango_rp = _rango(rp_f)
        rango_goles = _rango(gol_f)
        if rango_rp is not None and rango_goles is not None:
            volatilidad = rango_rp + rango_goles

        return {
            "partidos": len([e for e in (lista_est or []) if e]),
            "partidos_marcador": partidos_marcador,
            "media_remates_f": _media(rem_f),
            "media_remates_c": _media(rem_c),
            "media_rp_f": _media(rp_f),
            "media_rp_c": _media(rp_c),
            "media_corners_f": _media(cor_f),
            "media_corners_c": _media(cor_c),
            "media_amarillas_f": _media(am_f),
            "media_amarillas_c": _media(am_c),
            "media_goles_f": _media(gol_f),
            "media_goles_c": _media(gol_c),
            "eficiencia_remate": _safe_div(sum(gol_f), sum(rp_f)) if rp_f else None,
            "precision_tiro": _safe_div(sum(rp_f), sum(rem_f)) if rem_f else None,
            "dominio_ofensivo_neto": dom_rem,
            "dominio_puerta_neto": dom_rp,
            "dominio_territorial_neto": dom_cor,
            "intensidad_partido": _media(intensidad),
            "agresividad": _media(agresividad),
            "tendencia_dominio": tendencia_dominio,
            "volatilidad": volatilidad,
            "indice_dominio": indice_dominio,
            "indice_riesgo_gol": (_media(rp_f) + _media(rp_c)) if (_media(rp_f) is not None and _media(rp_c) is not None) else None,
            "over15_rate": _safe_div(over15, partidos_marcador),
            "btts_rate": _safe_div(btts, partidos_marcador),
        }

    def _nivel_confianza(score):
        if score >= 75:
            return "ALTA"
        if score >= 60:
            return "MEDIA"
        return "BAJA"

    def _etiqueta_ratio(valor):
        if valor is None:
            return "SIN DATO"
        if valor >= 0.40:
            return "ALTO"
        if valor >= 0.28:
            return "MEDIO"
        return "BAJO"

    def _etiqueta_neto(valor):
        if valor is None:
            return "SIN DATO"
        if valor >= 1.50:
            return "ALTO POSITIVO"
        if valor >= 0.40:
            return "MEDIO POSITIVO"
        if valor > -0.40:
            return "NEUTRO"
        if valor > -1.50:
            return "MEDIO NEGATIVO"
        return "ALTO NEGATIVO"

    def _etiqueta_intensidad(valor):
        if valor is None:
            return "SIN DATO"
        if valor >= 38:
            return "ALTA"
        if valor >= 30:
            return "MEDIA"
        return "BAJA"

    def _etiqueta_agresividad(valor):
        if valor is None:
            return "SIN DATO"
        if valor >= 5.0:
            return "ALTA"
        if valor >= 3.6:
            return "MEDIA"
        return "BAJA"

    def _etiqueta_volatilidad(valor):
        if valor is None:
            return "SIN DATO"
        if valor >= 7:
            return "ALTA"
        if valor >= 4:
            return "MEDIA"
        return "BAJA"

    def _etiqueta_tendencia(valor):
        if valor is None:
            return "SIN DATO"
        if valor >= 1.2:
            return "ALCISTA"
        if valor >= 0.2:
            return "LIGERAMENTE ALCISTA"
        if valor > -0.2:
            return "PLANA"
        if valor > -1.2:
            return "LIGERAMENTE BAJISTA"
        return "BAJISTA"

    def _texto_presentacion(nombre, av, res):
        dominio = av.get("indice_dominio")
        tendencia = av.get("tendencia_dominio")
        intensidad = av.get("intensidad_partido")
        riesgo = av.get("indice_riesgo_gol")
        precision = av.get("precision_tiro")
        eficiencia = av.get("eficiencia_remate")

        if dominio is None:
            lectura_dominio = "sin suficiente informacion de dominio"
        elif dominio >= 1.5:
            lectura_dominio = "con superioridad estadistica clara"
        elif dominio >= 0.4:
            lectura_dominio = "con ligera ventaja estadistica"
        elif dominio > -0.4:
            lectura_dominio = "en un escenario equilibrado"
        elif dominio > -1.5:
            lectura_dominio = "con desventaja estadistica moderada"
        else:
            lectura_dominio = "con desventaja estadistica clara"

        if tendencia is None:
            lectura_tendencia = "sin tendencia reciente definida"
        elif tendencia >= 0.8:
            lectura_tendencia = "y una dinamica reciente positiva"
        elif tendencia > -0.8:
            lectura_tendencia = "y una dinamica reciente estable"
        else:
            lectura_tendencia = "y una dinamica reciente negativa"

        if intensidad is None:
            lectura_ritmo = "ritmo incierto"
        elif intensidad >= 38:
            lectura_ritmo = "ritmo alto"
        elif intensidad >= 30:
            lectura_ritmo = "ritmo medio"
        else:
            lectura_ritmo = "ritmo bajo"

        if riesgo is None:
            lectura_riesgo = "riesgo de gol sin dato"
        elif riesgo >= 9:
            lectura_riesgo = "riesgo de gol alto"
        elif riesgo >= 7:
            lectura_riesgo = "riesgo de gol medio"
        else:
            lectura_riesgo = "riesgo de gol bajo"

        if precision is None or eficiencia is None:
            lectura_ataque = "ataque sin dato completo"
        elif precision >= 0.35 and eficiencia >= 0.30:
            lectura_ataque = "ataque eficiente"
        elif precision >= 0.28 or eficiencia >= 0.24:
            lectura_ataque = "ataque aceptable"
        else:
            lectura_ataque = "ataque poco eficiente"

        return (
            f"  {nombre}: llega {lectura_dominio}, {lectura_tendencia}; "
            f"presenta {lectura_ataque}, {lectura_ritmo} y {lectura_riesgo}. "
            f"Balance reciente: {res['ganados']}G-{res['empatados']}E-{res['perdidos']}P."
        )

    def _tramo_clasificacion(datos):
        if not datos:
            return "sin contexto clasificatorio"
        rank = datos.get("rank")
        zone = (datos.get("zone") or "").lower()
        total = total_equipos_liga or 20
        if "zone-1" in zone:
            return "en zona de descenso"
        if "zone1" in zone or "zone2" in zone or "zone3" in zone:
            return "en zona alta o europea"
        if rank is None:
            return "sin posicion definida"
        tercio = max(total / 3.0, 1)
        if rank <= tercio:
            return "en la zona alta"
        if rank >= total - tercio + 1:
            return "en la zona baja"
        return "en la zona media"

    def _etiqueta_forma_liga(form_points):
        if form_points is None:
            return "forma reciente sin dato"
        if form_points >= 10:
            return "muy buena dinamica liguera"
        if form_points >= 7:
            return "dinamica liguera positiva"
        if form_points >= 5:
            return "dinamica liguera intermedia"
        return "dinamica liguera floja"

    def _perfil_goles_liga(datos):
        if not datos:
            return "perfil goleador sin referencia de liga"
        avg_goals = datos.get("avg_goals")
        over25 = datos.get("over25_pct")
        btts = datos.get("btts_pct")
        failed = datos.get("failed_to_score_pct")
        clean = datos.get("clean_sheet_pct")

        if avg_goals is not None and avg_goals >= 3.0:
            perfil = "partidos muy abiertos"
        elif avg_goals is not None and avg_goals >= 2.5:
            perfil = "partidos de ritmo medio-alto"
        else:
            perfil = "partidos mas cerrados"

        matiz = []
        if over25 is not None and over25 >= 0.58:
            matiz.append("tendencia alta al +2.5")
        elif over25 is not None and over25 <= 0.42:
            matiz.append("tendencia baja al +2.5")
        if btts is not None and btts >= 0.60:
            matiz.append("muchos intercambios de gol")
        elif btts is not None and btts <= 0.42:
            matiz.append("pocos partidos con ambos marcando")
        if failed is not None and failed >= 0.32:
            matiz.append("riesgo notable de quedarse sin marcar")
        if clean is not None and clean >= 0.30:
            matiz.append("buena capacidad para dejar la porteria a cero")
        return perfil + (f" ({'; '.join(matiz)})" if matiz else "")

    def _lineas_como_llega_equipo(nombre, datos, av, res):
        base = [_texto_presentacion(nombre, av, res)]
        if not datos:
            base.append(f"  {nombre}: sin datos de clasificacion de liga para ampliar el analisis.")
            return base

        form_points = _puntos_forma(datos.get("form"))
        base.append(
            f"  {nombre}: { _tramo_clasificacion(datos) }, puesto { _formato_valor(datos.get('rank')) } de "
            f"{ _formato_valor(total_equipos_liga) }, con { _formato_valor(datos.get('points')) } puntos en "
            f"{ _formato_valor(datos.get('mp')) } jornadas y balance "
            f"{ _formato_valor(datos.get('wins')) }V-{ _formato_valor(datos.get('draws')) }E-{ _formato_valor(datos.get('losses')) }D."
        )
        base.append(
            f"  {nombre}: produce { _formato_decimal(datos.get('gf_pg')) } goles por partido y encaja "
            f"{ _formato_decimal(datos.get('ga_pg')) }; total { _formato_valor(datos.get('gf')) } GF y "
            f"{ _formato_valor(datos.get('ga')) } GC, con diferencia { _formato_valor(datos.get('gd')) } y PPP "
            f"{ _formato_decimal(datos.get('ppg')) }."
        )
        base.append(
            f"  {nombre}: { _etiqueta_forma_liga(form_points) }, ultimos 5 de liga {datos.get('form') or '-'} "
            f"({ _formato_valor(form_points) }/15 puntos). Porterias a cero "
            f"{ _formato_decimal((datos.get('clean_sheet_pct') or 0) * 100) }%, ambos marcan "
            f"{ _formato_decimal((datos.get('btts_pct') or 0) * 100) }%, sin marcar "
            f"{ _formato_decimal((datos.get('failed_to_score_pct') or 0) * 100) }%."
        )
        base.append(
            f"  {nombre}: { _perfil_goles_liga(datos) }. Over 1.5 "
            f"{ _formato_decimal((datos.get('over15_pct') or 0) * 100) }%, over 2.5 "
            f"{ _formato_decimal((datos.get('over25_pct') or 0) * 100) }%, media total de goles "
            f"{ _formato_decimal(datos.get('avg_goals')) }."
        )
        return base

    def _lineas_lectura_cruce(local_d, visit_d, av_local_d, av_visit_d):
        if not local_d or not visit_d:
            return []

        gap_rank = (visit_d.get("rank") or 0) - (local_d.get("rank") or 0)
        gap_ppg = (local_d.get("ppg") or 0) - (visit_d.get("ppg") or 0)
        gap_gf = (local_d.get("gf_pg") or 0) - (visit_d.get("gf_pg") or 0)
        gap_ga = (visit_d.get("ga_pg") or 0) - (local_d.get("ga_pg") or 0)
        gap_cs = (local_d.get("clean_sheet_pct") or 0) - (visit_d.get("clean_sheet_pct") or 0)
        gap_fts = (visit_d.get("failed_to_score_pct") or 0) - (local_d.get("failed_to_score_pct") or 0)
        media_over25 = ((local_d.get("over25_pct") or 0) + (visit_d.get("over25_pct") or 0)) / 2
        media_btts = ((local_d.get("btts_pct") or 0) + (visit_d.get("btts_pct") or 0)) / 2
        media_avg = ((local_d.get("avg_goals") or 0) + (visit_d.get("avg_goals") or 0)) / 2

        if gap_ppg >= 0.35 or gap_rank >= 4:
            ventaja_tabla = local
        elif gap_ppg <= -0.35 or gap_rank <= -4:
            ventaja_tabla = visitante
        else:
            ventaja_tabla = None

        if gap_gf >= 0.25 and gap_ga >= 0.15:
            perfil_fuerza = f"{local} combina mejor ataque y mejor estructura defensiva"
        elif gap_gf <= -0.25 and gap_ga <= -0.15:
            perfil_fuerza = f"{visitante} combina mejor ataque y mejor estructura defensiva"
        elif gap_gf >= 0.25:
            perfil_fuerza = f"{local} llega con mayor produccion ofensiva"
        elif gap_gf <= -0.25:
            perfil_fuerza = f"{visitante} llega con mayor produccion ofensiva"
        elif gap_ga >= 0.15:
            perfil_fuerza = f"{local} ofrece una defensa mas fiable"
        elif gap_ga <= -0.15:
            perfil_fuerza = f"{visitante} ofrece una defensa mas fiable"
        else:
            perfil_fuerza = "no hay una superioridad clara entre ataque y defensa de ambos"

        if media_avg >= 2.75 or media_over25 >= 0.55:
            sesgo_goles = "el cruce apunta a un partido con tendencia a goles"
        elif media_avg <= 2.35 and media_over25 <= 0.45:
            sesgo_goles = "el cruce apunta a un partido mas contenido"
        else:
            sesgo_goles = "el cruce no marca un sesgo fuerte de goles"

        if media_btts >= 0.58:
            sesgo_btts = "hay base estadistica para intercambio de gol"
        elif media_btts <= 0.42:
            sesgo_btts = "hay base estadistica para que no marquen ambos"
        else:
            sesgo_btts = "el ambos marcan queda en zona intermedia"

        lectura = []
        if ventaja_tabla:
            lectura.append(
                f"  Lectura comparativa: la tabla favorece a {ventaja_tabla}, con gap de posicion {abs(gap_rank)} "
                f"puestos y diferencia PPP de { _formato_decimal(abs(gap_ppg)) }."
            )
        else:
            lectura.append(
                f"  Lectura comparativa: clasificacion bastante pareja, con gap de posicion {abs(gap_rank)} "
                f"puestos y diferencia PPP de { _formato_decimal(abs(gap_ppg)) }."
            )
        lectura.append(f"  Lectura comparativa: {perfil_fuerza}.")
        lectura.append(
            f"  Lectura comparativa: {sesgo_goles}; media combinada de goles { _formato_decimal(media_avg) }, "
            f"over 2.5 medio { _formato_decimal(media_over25 * 100) }%, BTTS medio { _formato_decimal(media_btts * 100) }% "
            f"y ademas {sesgo_btts}."
        )

        if gap_cs >= 0.10 or gap_fts >= 0.10:
            lectura.append(
                f"  Lectura comparativa: {local} tiene mas argumentos para sostener ventaja defensiva "
                f"(Pa0 { _formato_decimal((local_d.get('clean_sheet_pct') or 0) * 100) }% vs "
                f"{ _formato_decimal((visit_d.get('clean_sheet_pct') or 0) * 100) }%; "
                f"PSM rival { _formato_decimal((visit_d.get('failed_to_score_pct') or 0) * 100) }%)."
            )
        elif gap_cs <= -0.10 or gap_fts <= -0.10:
            lectura.append(
                f"  Lectura comparativa: {visitante} tiene mejor soporte para competir desde la solidez "
                f"(Pa0 { _formato_decimal((visit_d.get('clean_sheet_pct') or 0) * 100) }% vs "
                f"{ _formato_decimal((local_d.get('clean_sheet_pct') or 0) * 100) }%; "
                f"PSM rival { _formato_decimal((local_d.get('failed_to_score_pct') or 0) * 100) }%)."
            )

        indice_duelo = (av_local_d.get("indice_dominio") or 0) - (av_visit_d.get("indice_dominio") or 0)
        if abs(indice_duelo) >= 0.8:
            lectura.append(
                f"  Sintesis del partido: la forma reciente pesa mas que la tabla y tambien inclina el duelo hacia "
                f"{local if indice_duelo > 0 else visitante}."
            )
        else:
            lectura.append(
                "  Sintesis del partido: la tabla orienta, pero la forma reciente manda una lectura corta mas equilibrada."
            )
        return lectura

    def _senales_mercado(av_local, av_visitante, av_h2h=None, liga_local=None, liga_visitante=None):
        def v(x, default=0.0):
            return x if x is not None else default

        proj_sot_local = (v(av_local.get("media_rp_f")) + v(av_visitante.get("media_rp_c"))) / 2
        proj_sot_visit = (v(av_visitante.get("media_rp_f")) + v(av_local.get("media_rp_c"))) / 2
        proj_sot_total = proj_sot_local + proj_sot_visit

        proj_goles_local = (v(av_local.get("media_goles_f")) + v(av_visitante.get("media_goles_c"))) / 2
        proj_goles_visit = (v(av_visitante.get("media_goles_f")) + v(av_local.get("media_goles_c"))) / 2
        proj_goles_total = proj_goles_local + proj_goles_visit

        proj_corners_for = v(av_local.get("media_corners_f")) + v(av_visitante.get("media_corners_f"))
        proj_corners_against = v(av_local.get("media_corners_c")) + v(av_visitante.get("media_corners_c"))
        proj_corners_total = (proj_corners_for + proj_corners_against) / 2

        proj_tarjetas_total = (v(av_local.get("agresividad")) + v(av_visitante.get("agresividad"))) / 2

        score_over15 = 0
        if proj_sot_total >= 8:
            score_over15 += 45
        elif proj_sot_total >= 6:
            score_over15 += 30
        if proj_goles_total >= 2.2:
            score_over15 += 35
        elif proj_goles_total >= 1.8:
            score_over15 += 20
        if av_h2h and av_h2h.get("over15_rate") is not None:
            score_over15 += 20 if av_h2h["over15_rate"] >= 0.6 else 10
        if liga_local and liga_visitante:
            avg_goles_liga = (v(liga_local.get("avg_goals")) + v(liga_visitante.get("avg_goals"))) / 2
            avg_over15_liga = (v(liga_local.get("over15_pct")) + v(liga_visitante.get("over15_pct"))) / 2
            if avg_goles_liga >= 2.8:
                score_over15 += 10
            if avg_over15_liga >= 0.80:
                score_over15 += 10
        score_over15 = min(score_over15, 100)

        score_btts = 0
        if proj_sot_local >= 3 and proj_sot_visit >= 3:
            score_btts += 45
        elif proj_sot_total >= 6:
            score_btts += 25
        if proj_goles_local >= 0.9 and proj_goles_visit >= 0.9:
            score_btts += 35
        elif proj_goles_total >= 2.0:
            score_btts += 20
        if av_h2h and av_h2h.get("btts_rate") is not None:
            score_btts += 20 if av_h2h["btts_rate"] >= 0.55 else 10
        if liga_local and liga_visitante:
            avg_btts_liga = (v(liga_local.get("btts_pct")) + v(liga_visitante.get("btts_pct"))) / 2
            if avg_btts_liga >= 0.58:
                score_btts += 12
        score_btts = min(score_btts, 100)

        score_corners = 0
        if proj_corners_total >= 10:
            score_corners += 55
        elif proj_corners_total >= 9:
            score_corners += 40
        elif proj_corners_total >= 8:
            score_corners += 25
        if abs(v(av_local.get("dominio_territorial_neto")) - v(av_visitante.get("dominio_territorial_neto"))) <= 1.5:
            score_corners += 20
        if v(av_local.get("intensidad_partido")) + v(av_visitante.get("intensidad_partido")) >= 45:
            score_corners += 20
        score_corners = min(score_corners, 100)

        score_tarjetas = 0
        if proj_tarjetas_total >= 4.5:
            score_tarjetas += 60
        elif proj_tarjetas_total >= 3.8:
            score_tarjetas += 45
        elif proj_tarjetas_total >= 3.2:
            score_tarjetas += 25
        if av_h2h and av_h2h.get("agresividad") is not None:
            if av_h2h["agresividad"] >= 4.5:
                score_tarjetas += 25
            elif av_h2h["agresividad"] >= 3.8:
                score_tarjetas += 15
        score_tarjetas = min(score_tarjetas, 100)

        score_dnb_local = 0
        gap_dominio = v(av_local.get("indice_dominio")) - v(av_visitante.get("indice_dominio"))
        if gap_dominio >= 1.2:
            score_dnb_local += 45
        elif gap_dominio >= 0.5:
            score_dnb_local += 30
        if v(av_local.get("tendencia_dominio")) > 0:
            score_dnb_local += 20
        if proj_goles_local >= proj_goles_visit:
            score_dnb_local += 20
        if av_h2h and av_h2h.get("indice_dominio") is not None and av_h2h["indice_dominio"] > 0:
            score_dnb_local += 15
        if liga_local and liga_visitante:
            gap_ppg = v(liga_local.get("ppg")) - v(liga_visitante.get("ppg"))
            gap_pos = v(liga_visitante.get("rank")) - v(liga_local.get("rank"))
            if gap_ppg >= 0.35:
                score_dnb_local += 15
            elif gap_ppg >= 0.15:
                score_dnb_local += 8
            if gap_pos >= 4:
                score_dnb_local += 10
        score_dnb_local = min(score_dnb_local, 100)

        return {
            "proj_goles_local": proj_goles_local,
            "proj_goles_visit": proj_goles_visit,
            "proj_sot_total": proj_sot_total,
            "proj_goles_total": proj_goles_total,
            "proj_corners_total": proj_corners_total,
            "proj_tarjetas_total": proj_tarjetas_total,
            "over15": (score_over15, _nivel_confianza(score_over15)),
            "btts": (score_btts, _nivel_confianza(score_btts)),
            "over85_corners": (score_corners, _nivel_confianza(score_corners)),
            "over35_tarjetas": (score_tarjetas, _nivel_confianza(score_tarjetas)),
            "dnb_local": (score_dnb_local, _nivel_confianza(score_dnb_local)),
        }

    def _pronostico_partido(
        local_nombre,
        visitante_nombre,
        av_local_d,
        av_visit_d,
        señales,
        liga_local_d=None,
        liga_visit_d=None,
        res_local_d=None,
        res_visit_d=None,
        score_local_casa_d=None,
        score_visit_fuera_d=None,
    ):
        def v(x, default=0.0):
            return x if x is not None else default

        gol_local_base = v(señales.get("proj_goles_local"))
        gol_visit_base = v(señales.get("proj_goles_visit"))
        gap_gol = gol_local_base - gol_visit_base
        gap_dominio = v(av_local_d.get("indice_dominio")) - v(av_visit_d.get("indice_dominio"))
        gap_tendencia = v(av_local_d.get("tendencia_dominio")) - v(av_visit_d.get("tendencia_dominio"))
        gap_ppg = v((liga_local_d or {}).get("ppg")) - v((liga_visit_d or {}).get("ppg"))
        gap_pos = v((liga_visit_d or {}).get("rank")) - v((liga_local_d or {}).get("rank"))
        gap_racha = v(_score_racha(res_local_d), 0.5) - v(_score_racha(res_visit_d), 0.5)
        gap_condicion = (v(score_local_casa_d, 50.0) - v(score_visit_fuera_d, 50.0)) / 10.0

        score_local = 50.0
        score_local += gap_gol * 16
        score_local += gap_dominio * 9
        score_local += gap_tendencia * 10
        score_local += gap_racha * 30
        score_local += gap_condicion * 4
        score_local += gap_ppg * 7
        score_local += max(min(gap_pos, 8), -8) * 1.0
        score_local = max(0, min(100, score_local))

        if score_local >= 64:
            pick_1x2 = "1"
            lectura = f"victoria probable de {local_nombre}"
        elif score_local <= 36:
            pick_1x2 = "2"
            lectura = f"victoria probable de {visitante_nombre}"
        else:
            pick_1x2 = "X"
            lectura = "empate como escenario principal"

        confianza = _nivel_confianza(abs(score_local - 50) * 2)

        ajuste = (score_local - 50) / 100.0
        gol_local = max(0, gol_local_base + ajuste * 0.6)
        gol_visit = max(0, gol_visit_base - ajuste * 0.6)

        base_local = max(0, round(gol_local))
        base_visit = max(0, round(gol_visit))
        candidatos = [
            (base_local, base_visit),
            (max(0, base_local + 1), base_visit),
            (base_local, max(0, base_visit + 1)),
            (max(0, base_local - 1), base_visit),
            (base_local, max(0, base_visit - 1)),
            (max(0, base_local + 1), max(0, base_visit + 1)),
            (1, 1),
            (1, 0),
            (2, 1),
            (2, 0),
            (0, 1),
            (1, 2),
        ]

        unicos = []
        vistos = set()
        for marcador in candidatos:
            if marcador not in vistos:
                vistos.add(marcador)
                unicos.append(marcador)

        def score_marcador(m):
            gl, gv = m
            score = 10.0
            score -= abs(gl - gol_local) * 4.0
            score -= abs(gv - gol_visit) * 4.0
            if pick_1x2 == "1" and gl > gv:
                score += 2.5
            elif pick_1x2 == "2" and gv > gl:
                score += 2.5
            elif pick_1x2 == "X" and gl == gv:
                score += 2.5
            if señales["btts"][0] >= 60 and gl > 0 and gv > 0:
                score += 1.5
            if señales["over15"][0] >= 60 and (gl + gv) >= 2:
                score += 1.0
            if señales["over15"][0] < 45 and (gl + gv) <= 2:
                score += 1.0
            return score

        mejores = sorted(unicos, key=score_marcador, reverse=True)[:3]
        return {
            "pick_1x2": pick_1x2,
            "lectura": lectura,
            "confianza": confianza,
            "score_local": score_local,
            "goles_ajustados_local": gol_local,
            "goles_ajustados_visit": gol_visit,
            "marcadores": mejores,
        }

    def _resumen_resultados(lista_est):
        resumen = {"ganados": 0, "empatados": 0, "perdidos": 0, "con_marcador": 0, "sin_marcador": 0}
        for est in lista_est or []:
            if not est:
                resumen["sin_marcador"] += 1
                continue
            goles_eq = est.get("goles_equipo")
            goles_riv = est.get("goles_rival")
            if goles_eq is None or goles_riv is None:
                resumen["sin_marcador"] += 1
                continue
            resumen["con_marcador"] += 1
            if goles_eq > goles_riv:
                resumen["ganados"] += 1
            elif goles_eq == goles_riv:
                resumen["empatados"] += 1
            else:
                resumen["perdidos"] += 1
        return resumen

    def _filtrar_partidos_por_condicion(lista_est, condicion):
        filtrados = []
        for est in lista_est or []:
            if not est:
                continue
            es_local = _coincide_equipo(est.get("local", ""), est.get("equipo", ""))
            if condicion == "local" and es_local:
                filtrados.append(est)
            elif condicion == "visitante" and not es_local:
                filtrados.append(est)
        return filtrados

    def _score_racha(resumen):
        if not resumen or not resumen.get("con_marcador"):
            return None
        puntos = resumen["ganados"] * 3 + resumen["empatados"]
        return puntos / max(resumen["con_marcador"] * 3, 1)

    def _score_rendimiento_condicion(lista_est):
        if not lista_est:
            return None
        av = _resumen_avanzado(lista_est)
        res = _resumen_resultados(lista_est)
        score = 50.0
        score += (av.get("indice_dominio") or 0) * 9
        score += (av.get("tendencia_dominio") or 0) * 7
        score += ((av.get("media_goles_f") or 0) - (av.get("media_goles_c") or 0)) * 12
        score += ((av.get("media_rp_f") or 0) - (av.get("media_rp_c") or 0)) * 4
        racha = _score_racha(res)
        if racha is not None:
            score += (racha - 0.5) * 36
        return max(0, min(100, score))

    def _etiqueta_condicion(score):
        if score is None:
            return "sin muestra suficiente"
        if score >= 66:
            return "fortaleza clara"
        if score >= 56:
            return "rendimiento favorable"
        if score >= 44:
            return "rendimiento equilibrado"
        return "rendimiento fragil"

    def bloque_equipo(titulo, lista_est, equipo_ref):
        lineas.append("")
        lineas.append("-" * 70)
        lineas.append(f"  {titulo}")
        lineas.append("-" * 70)
        if not lista_est:
            lineas.append("  (Sin datos)")
            return _resumen_superioridad([], equipo_ref), _resumen_metricas(lista_est)
        for idx, est in enumerate(lista_est, 1):
            if not est:
                lineas.append(f"  Partido {idx}: datos no disponibles")
                continue
            eq = est.get("equipo", "?")
            riv = est.get("rival", "?")
            local_real = est.get("local") or eq
            visitante_real = est.get("visitante") or riv
            g_local = _formato_valor(est.get("goles_local"))
            g_visitante = _formato_valor(est.get("goles_visitante"))
            lineas.append("")
            lineas.append(
                f"  Partido {idx}:  {local_real}  vs  {visitante_real}   |   Resultado: {g_local} - {g_visitante}"
            )
            lineas.append("  " + "-" * 50)
            lineas.append(f"    Remates totales:    {eq} {_formato_valor(est.get('remates_favor'))}  |  {riv} {_formato_valor(est.get('remates_contra'))}")
            lineas.append(f"    Remates a puerta:  {eq} {_formato_valor(est.get('remates_puerta_favor'))}  |  {riv} {_formato_valor(est.get('remates_puerta_contra'))}")
            lineas.append(f"    Corners:           {eq} {_formato_valor(est.get('corners_favor'))}  |  {riv} {_formato_valor(est.get('corners_contra'))}")
            lineas.append(f"    Tarjetas amarillas: {eq} {_formato_valor(est.get('amarillas_favor'))}  |  {riv} {_formato_valor(est.get('amarillas_contra'))}")
            lineas.append(f"    URL partido: {est.get('url')}")

        resumen = _resumen_superioridad(lista_est, equipo_ref)
        metricas = _resumen_metricas(lista_est)
        lineas.append("")
        lineas.append(f"  Resumen {resumen['total']} partidos:")
        lineas.append(
            f"    Mas remates: {resumen['remates']} | "
            f"Mas remates a puerta: {resumen['remates_puerta']} | "
            f"Mas corners: {resumen['corners']} | "
            f"Mas amarillas: {resumen['amarillas']}"
        )
        lineas.append(
            f"    Como local ({resumen['local_total']}): "
            f"Mas remates {resumen['local']['remates']} | "
            f"Mas remates a puerta {resumen['local']['remates_puerta']} | "
            f"Mas corners {resumen['local']['corners']} | "
            f"Mas amarillas {resumen['local']['amarillas']}"
        )
        lineas.append(
            f"    Como visitante ({resumen['visit_total']}): "
            f"Mas remates {resumen['visit']['remates']} | "
            f"Mas remates a puerta {resumen['visit']['remates_puerta']} | "
            f"Mas corners {resumen['visit']['corners']} | "
            f"Mas amarillas {resumen['visit']['amarillas']}"
        )
        lineas.append("    Estadisticas agregadas:")
        lineas.append(_linea_metrica("Remates", metricas["remates"], metricas["remates_contra"]))
        lineas.append(_linea_metrica("Remates a puerta", metricas["remates_puerta"], metricas["remates_puerta_contra"]))
        lineas.append(_linea_metrica("Corners", metricas["corners"], metricas["corners_contra"]))
        lineas.append(_linea_metrica("Tarjetas amarillas", metricas["amarillas"], metricas["amarillas_contra"]))
        return resumen, metricas

    resumen_local, metricas_local = bloque_equipo(
        f"ULTIMOS {MAX_PARTIDOS} PARTIDOS DE {local.upper()}",
        estadisticas_local,
        local,
    )
    resumen_visitante, metricas_visitante = bloque_equipo(
        f"ULTIMOS {MAX_PARTIDOS} PARTIDOS DE {visitante.upper()}",
        estadisticas_visitante,
        visitante,
    )

    resumen_enfrentamientos, metricas_enfrentamientos = bloque_equipo(
        f"ENFRENTAMIENTOS DIRECTOS {local.upper()} vs {visitante.upper()}",
        estadisticas_enfrentamientos or [],
        local,
    )

    lineas.append("")
    lineas.append("-" * 70)
    lineas.append("  RESUMEN GLOBAL (LOCAL EN CASA VS VISITANTE FUERA)")
    lineas.append("-" * 70)
    lineas.append(
        f"  {local} como local: {resumen_local['local_total']} partidos, "
        f"con mas remates en {resumen_local['local']['remates']}, "
        f"mas remates a puerta en {resumen_local['local']['remates_puerta']}, "
        f"mas corners en {resumen_local['local']['corners']} y "
        f"mas amarillas en {resumen_local['local']['amarillas']}."
    )
    lineas.append(
        f"  Medias {local}: remates {_formato_decimal(metricas_local['remates']['media'])}, "
        f"remates a puerta {_formato_decimal(metricas_local['remates_puerta']['media'])}, "
        f"corners {_formato_decimal(metricas_local['corners']['media'])}, "
        f"amarillas {_formato_decimal(metricas_local['amarillas']['media'])}."
    )
    lineas.append(
        f"  Max/Min {local}: remates { _formato_valor(metricas_local['remates']['max']) }/{ _formato_valor(metricas_local['remates']['min']) }, "
        f"remates a puerta { _formato_valor(metricas_local['remates_puerta']['max']) }/{ _formato_valor(metricas_local['remates_puerta']['min']) }, "
        f"corners { _formato_valor(metricas_local['corners']['max']) }/{ _formato_valor(metricas_local['corners']['min']) }, "
        f"amarillas { _formato_valor(metricas_local['amarillas']['max']) }/{ _formato_valor(metricas_local['amarillas']['min']) }."
    )
    lineas.append(
        f"  {visitante} como visitante: {resumen_visitante['visit_total']} partidos, "
        f"con mas remates en {resumen_visitante['visit']['remates']}, "
        f"mas remates a puerta en {resumen_visitante['visit']['remates_puerta']}, "
        f"mas corners en {resumen_visitante['visit']['corners']} y "
        f"mas amarillas en {resumen_visitante['visit']['amarillas']}."
    )
    lineas.append(
        f"  Medias {visitante}: remates {_formato_decimal(metricas_visitante['remates']['media'])}, "
        f"remates a puerta {_formato_decimal(metricas_visitante['remates_puerta']['media'])}, "
        f"corners {_formato_decimal(metricas_visitante['corners']['media'])}, "
        f"amarillas {_formato_decimal(metricas_visitante['amarillas']['media'])}."
    )
    lineas.append(
        f"  Max/Min {visitante}: remates { _formato_valor(metricas_visitante['remates']['max']) }/{ _formato_valor(metricas_visitante['remates']['min']) }, "
        f"remates a puerta { _formato_valor(metricas_visitante['remates_puerta']['max']) }/{ _formato_valor(metricas_visitante['remates_puerta']['min']) }, "
        f"corners { _formato_valor(metricas_visitante['corners']['max']) }/{ _formato_valor(metricas_visitante['corners']['min']) }, "
        f"amarillas { _formato_valor(metricas_visitante['amarillas']['max']) }/{ _formato_valor(metricas_visitante['amarillas']['min']) }."
    )
    if estadisticas_enfrentamientos:
        total_enf = resumen_enfrentamientos['total'] if resumen_enfrentamientos else 0
        lineas.append(
            f"  Enfrentamientos directos ({total_enf} partidos): "
            f"mas remates en {resumen_enfrentamientos['remates']}, "
            f"mas remates a puerta en {resumen_enfrentamientos['remates_puerta']}, "
            f"mas corners en {resumen_enfrentamientos['corners']} y "
            f"mas amarillas en {resumen_enfrentamientos['amarillas']} "
            f"(perspectiva {local})."
        )
        lineas.append(
            f"  Medias enfrentamientos: remates {_formato_decimal(metricas_enfrentamientos['remates']['media'])}, "
            f"remates a puerta {_formato_decimal(metricas_enfrentamientos['remates_puerta']['media'])}, "
            f"corners {_formato_decimal(metricas_enfrentamientos['corners']['media'])}, "
            f"amarillas {_formato_decimal(metricas_enfrentamientos['amarillas']['media'])}."
        )
        lineas.append(
            f"  Max/Min enfrentamientos: remates { _formato_valor(metricas_enfrentamientos['remates']['max']) }/{ _formato_valor(metricas_enfrentamientos['remates']['min']) }, "
            f"remates a puerta { _formato_valor(metricas_enfrentamientos['remates_puerta']['max']) }/{ _formato_valor(metricas_enfrentamientos['remates_puerta']['min']) }, "
            f"corners { _formato_valor(metricas_enfrentamientos['corners']['max']) }/{ _formato_valor(metricas_enfrentamientos['corners']['min']) }, "
            f"amarillas { _formato_valor(metricas_enfrentamientos['amarillas']['max']) }/{ _formato_valor(metricas_enfrentamientos['amarillas']['min']) }."
        )

    resultados_local = _resumen_resultados(estadisticas_local)
    resultados_visitante = _resumen_resultados(estadisticas_visitante)
    partidos_local_casa = _filtrar_partidos_por_condicion(estadisticas_local, "local")
    partidos_visitante_fuera = _filtrar_partidos_por_condicion(estadisticas_visitante, "visitante")
    resultados_local_casa = _resumen_resultados(partidos_local_casa)
    resultados_visitante_fuera = _resumen_resultados(partidos_visitante_fuera)

    lineas.append("")
    lineas.append("-" * 70)
    lineas.append("  RESUMEN RESULTADOS (G/E/P)")
    lineas.append("-" * 70)
    lineas.append(
        f"  {local}: en los ultimos {MAX_PARTIDOS}, ha ganado {resultados_local['ganados']}, "
        f"empatado {resultados_local['empatados']} y perdido {resultados_local['perdidos']} "
        f"(partidos con marcador: {resultados_local['con_marcador']})."
    )
    lineas.append(
        f"  {visitante}: en los ultimos {MAX_PARTIDOS}, ha ganado {resultados_visitante['ganados']}, "
        f"empatado {resultados_visitante['empatados']} y perdido {resultados_visitante['perdidos']} "
        f"(partidos con marcador: {resultados_visitante['con_marcador']})."
    )

    av_local = _resumen_avanzado(estadisticas_local)
    av_visitante = _resumen_avanzado(estadisticas_visitante)
    av_h2h = _resumen_avanzado(estadisticas_enfrentamientos or []) if estadisticas_enfrentamientos else None
    av_local_casa = _resumen_avanzado(partidos_local_casa)
    av_visitante_fuera = _resumen_avanzado(partidos_visitante_fuera)
    score_local_casa = _score_rendimiento_condicion(partidos_local_casa)
    score_visitante_fuera = _score_rendimiento_condicion(partidos_visitante_fuera)
    liga_local = (contexto_liga or {}).get("local") if contexto_liga else None
    liga_visitante = (contexto_liga or {}).get("visitante") if contexto_liga else None
    senales = _senales_mercado(av_local, av_visitante, av_h2h, liga_local, liga_visitante)

    lineas.append("")
    lineas.append("-" * 70)
    lineas.append("  INDICADORES AVANZADOS Y SENALES")
    lineas.append("-" * 70)
    lineas.append(
        f"  {local}: eficiencia remate {_formato_decimal(av_local['eficiencia_remate'])}, "
        f"[{_etiqueta_ratio(av_local['eficiencia_remate'])}], "
        f"precision tiro {_formato_decimal(av_local['precision_tiro'])}, "
        f"[{_etiqueta_ratio(av_local['precision_tiro'])}], "
        f"dominio neto remates {_formato_decimal(av_local['dominio_ofensivo_neto'])}, "
        f"[{_etiqueta_neto(av_local['dominio_ofensivo_neto'])}], "
        f"dominio neto puerta {_formato_decimal(av_local['dominio_puerta_neto'])}, "
        f"[{_etiqueta_neto(av_local['dominio_puerta_neto'])}], "
        f"dominio neto corners {_formato_decimal(av_local['dominio_territorial_neto'])}."
    )
    lineas.append(
        f"  {local}: intensidad {_formato_decimal(av_local['intensidad_partido'])}, "
        f"[{_etiqueta_intensidad(av_local['intensidad_partido'])}], "
        f"agresividad {_formato_decimal(av_local['agresividad'])}, "
        f"[{_etiqueta_agresividad(av_local['agresividad'])}], "
        f"tendencia reciente {_formato_decimal(av_local['tendencia_dominio'])}, "
        f"[{_etiqueta_tendencia(av_local['tendencia_dominio'])}], "
        f"volatilidad {_formato_decimal(av_local['volatilidad'])}, "
        f"[{_etiqueta_volatilidad(av_local['volatilidad'])}], "
        f"indice dominio {_formato_decimal(av_local['indice_dominio'])}, "
        f"[{_etiqueta_neto(av_local['indice_dominio'])}], "
        f"indice riesgo gol {_formato_decimal(av_local['indice_riesgo_gol'])}."
    )
    lineas.append(
        f"  {visitante}: eficiencia remate {_formato_decimal(av_visitante['eficiencia_remate'])}, "
        f"[{_etiqueta_ratio(av_visitante['eficiencia_remate'])}], "
        f"precision tiro {_formato_decimal(av_visitante['precision_tiro'])}, "
        f"[{_etiqueta_ratio(av_visitante['precision_tiro'])}], "
        f"dominio neto remates {_formato_decimal(av_visitante['dominio_ofensivo_neto'])}, "
        f"[{_etiqueta_neto(av_visitante['dominio_ofensivo_neto'])}], "
        f"dominio neto puerta {_formato_decimal(av_visitante['dominio_puerta_neto'])}, "
        f"[{_etiqueta_neto(av_visitante['dominio_puerta_neto'])}], "
        f"dominio neto corners {_formato_decimal(av_visitante['dominio_territorial_neto'])}."
    )
    lineas.append(
        f"  {visitante}: intensidad {_formato_decimal(av_visitante['intensidad_partido'])}, "
        f"[{_etiqueta_intensidad(av_visitante['intensidad_partido'])}], "
        f"agresividad {_formato_decimal(av_visitante['agresividad'])}, "
        f"[{_etiqueta_agresividad(av_visitante['agresividad'])}], "
        f"tendencia reciente {_formato_decimal(av_visitante['tendencia_dominio'])}, "
        f"[{_etiqueta_tendencia(av_visitante['tendencia_dominio'])}], "
        f"volatilidad {_formato_decimal(av_visitante['volatilidad'])}, "
        f"[{_etiqueta_volatilidad(av_visitante['volatilidad'])}], "
        f"indice dominio {_formato_decimal(av_visitante['indice_dominio'])}, "
        f"[{_etiqueta_neto(av_visitante['indice_dominio'])}], "
        f"indice riesgo gol {_formato_decimal(av_visitante['indice_riesgo_gol'])}."
    )

    if av_h2h:
        lineas.append(
            f"  H2H: over1.5 {_formato_decimal((av_h2h['over15_rate'] or 0) * 100)}%, "
            f"BTTS {_formato_decimal((av_h2h['btts_rate'] or 0) * 100)}%, "
            f"agresividad {_formato_decimal(av_h2h['agresividad'])}, "
            f"indice dominio {_formato_decimal(av_h2h['indice_dominio'])}."
        )

    lineas.append("  Proyecciones partido:")
    lineas.append(
        f"    Remates a puerta totales esperados: {_formato_decimal(senales['proj_sot_total'])} | "
        f"Goles totales esperados: {_formato_decimal(senales['proj_goles_total'])} | "
        f"Corners totales esperados: {_formato_decimal(senales['proj_corners_total'])} | "
        f"Tarjetas totales esperadas: {_formato_decimal(senales['proj_tarjetas_total'])}"
    )
    lineas.append("  Senales de mercado (orientativas):")
    lineas.append(
        f"    Over 1.5 goles -> score {senales['over15'][0]}/100 ({senales['over15'][1]})"
    )
    lineas.append(
        f"    Ambos marcan (BTTS) -> score {senales['btts'][0]}/100 ({senales['btts'][1]})"
    )
    lineas.append(
        f"    Over 8.5 corners -> score {senales['over85_corners'][0]}/100 ({senales['over85_corners'][1]})"
    )
    lineas.append(
        f"    Over 3.5 tarjetas -> score {senales['over35_tarjetas'][0]}/100 ({senales['over35_tarjetas'][1]})"
    )
    lineas.append(
        f"    Local empate no apuesta (DNB) -> score {senales['dnb_local'][0]}/100 ({senales['dnb_local'][1]})"
    )

    if liga_local or liga_visitante:
        lineas.append("")
        lineas.append("-" * 70)
        lineas.append("  CONTEXTO DE LIGA (FOOTYSTATS)")
        lineas.append("-" * 70)

        def _linea_liga(nombre_ref, datos):
            if not datos:
                return f"  {nombre_ref}: sin coincidencia en la tabla de FootyStats."
            return (
                f"  {nombre_ref}: puesto { _formato_valor(datos.get('rank')) }, "
                f"{ _formato_valor(datos.get('points')) } pts en { _formato_valor(datos.get('mp')) } PJ, "
                f"PPP { _formato_decimal(datos.get('ppg')) }, "
                f"GF/PJ { _formato_decimal(datos.get('gf_pg')) }, GC/PJ { _formato_decimal(datos.get('ga_pg')) }, "
                f"Pa0 { _formato_decimal((datos.get('clean_sheet_pct') or 0) * 100) }%, "
                f"AEM { _formato_decimal((datos.get('btts_pct') or 0) * 100) }%, "
                f"PSM { _formato_decimal((datos.get('failed_to_score_pct') or 0) * 100) }%, "
                f"+1.5 { _formato_decimal((datos.get('over15_pct') or 0) * 100) }%, "
                f"+2.5 { _formato_decimal((datos.get('over25_pct') or 0) * 100) }%, "
                f"MG { _formato_decimal(datos.get('avg_goals')) }, "
                f"ultimos5 {datos.get('form') or '-'}."
            )

        lineas.append(_linea_liga(local, liga_local))
        lineas.append(_linea_liga(visitante, liga_visitante))

        if liga_local and liga_visitante:
            gap_ppg = (liga_local.get("ppg") or 0) - (liga_visitante.get("ppg") or 0)
            gap_pos = (liga_visitante.get("rank") or 0) - (liga_local.get("rank") or 0)
            gap_racha = (_score_racha(resultados_local) or 0) - (_score_racha(resultados_visitante) or 0)
            gap_condicion = (score_local_casa or 50) - (score_visitante_fuera or 50)
            sesgo_goles = (
                ((liga_local.get("over25_pct") or 0) + (liga_visitante.get("over25_pct") or 0)) / 2
            )
            sesgo_btts = (
                ((liga_local.get("btts_pct") or 0) + (liga_visitante.get("btts_pct") or 0)) / 2
            )
            lineas.append(
                f"  Lectura liga: gap PPP {_formato_decimal(gap_ppg)} a favor de {local if gap_ppg >= 0 else visitante}; "
                f"diferencia de posicion {abs(gap_pos)} puestos; "
                f"gap racha reciente {_formato_decimal(gap_racha * 100)} pts porcentuales; "
                f"ventaja local/casa vs visitante/fuera {_formato_decimal(gap_condicion)} puntos; "
                f"sesgo +2.5 {_formato_decimal(sesgo_goles * 100)}%; "
                f"sesgo BTTS {_formato_decimal(sesgo_btts * 100)}%."
            )
            lineas.append(
                f"  Ajuste de contexto: {local} en casa [{_etiqueta_condicion(score_local_casa)}], "
                f"racha {_formato_valor(resultados_local_casa.get('ganados'))}V-"
                f"{_formato_valor(resultados_local_casa.get('empatados'))}E-"
                f"{_formato_valor(resultados_local_casa.get('perdidos'))}D, "
                f"indice dominio {_formato_decimal(av_local_casa.get('indice_dominio'))}, "
                f"tendencia {_formato_decimal(av_local_casa.get('tendencia_dominio'))}, "
                f"score {_formato_decimal(score_local_casa)}. "
                f"{visitante} fuera [{_etiqueta_condicion(score_visitante_fuera)}], "
                f"racha {_formato_valor(resultados_visitante_fuera.get('ganados'))}V-"
                f"{_formato_valor(resultados_visitante_fuera.get('empatados'))}E-"
                f"{_formato_valor(resultados_visitante_fuera.get('perdidos'))}D, "
                f"indice dominio {_formato_decimal(av_visitante_fuera.get('indice_dominio'))}, "
                f"tendencia {_formato_decimal(av_visitante_fuera.get('tendencia_dominio'))}, "
                f"score {_formato_decimal(score_visitante_fuera)}."
            )
        if contexto_liga and contexto_liga.get("url"):
            lineas.append(f"  Fuente liga: {contexto_liga['url']}")

    lineas.append("")
    lineas.append("-" * 70)
    lineas.append("  COMO LLEGAN AL PARTIDO")
    lineas.append("-" * 70)
    lineas.extend(_lineas_como_llega_equipo(local, liga_local, av_local, resultados_local))
    lineas.append("")
    lineas.extend(_lineas_como_llega_equipo(visitante, liga_visitante, av_visitante, resultados_visitante))
    lectura_cruce = _lineas_lectura_cruce(liga_local, liga_visitante, av_local, av_visitante)
    if lectura_cruce:
        lineas.append("")
        lineas.extend(lectura_cruce)
    pronostico = _pronostico_partido(
        local,
        visitante,
        av_local,
        av_visitante,
        senales,
        liga_local,
        liga_visitante,
        resultados_local,
        resultados_visitante,
        score_local_casa,
        score_visitante_fuera,
    )
    lineas.append("")
    lineas.append("-" * 70)
    lineas.append("  POSIBLE PRONOSTICO")
    lineas.append("-" * 70)
    lineas.append(
        f"  1X2 estimado: {pronostico['pick_1x2']} ({pronostico['lectura']}) | "
        f"confianza {pronostico['confianza']}."
    )
    lineas.append(
        f"  Base numerica: goles esperados ajustados {local} {_formato_decimal(pronostico['goles_ajustados_local'])} - "
        f"{_formato_decimal(pronostico['goles_ajustados_visit'])} {visitante} "
        f"(base cruda {_formato_decimal(senales['proj_goles_local'])} - {_formato_decimal(senales['proj_goles_visit'])}); "
        f"score local { _formato_decimal(pronostico['score_local']) }/100."
    )
    lineas.append(
        "  Marcadores correctos orientativos: "
        + " | ".join(f"{gl}-{gv}" for gl, gv in pronostico["marcadores"])
    )
    lineas.append("=" * 70)

    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))

    return ruta


def generar_informe_text(
    local,
    visitante,
    estadisticas_local,
    estadisticas_visitante,
    estadisticas_enfrentamientos=None,
    carpeta=None,
    contexto_liga=None,
):
    """Genera y devuelve el informe como texto (no escribe fichero)."""
    # Reuse the same building logic by calling generar_informe_txt but without writing
    # To avoid duplicating all code, replicate minimal behavior: call generar_informe_txt but capture contents
    # Simpler: temporarily write to a temp file in memory? We'll rebuild lines similarly by calling the shared blocks.
    # For reliability, call generar_informe_txt to create file, then read and remove it.
    ruta = generar_informe_txt(
        local,
        visitante,
        estadisticas_local,
        estadisticas_visitante,
        estadisticas_enfrentamientos,
        carpeta=carpeta,
        contexto_liga=contexto_liga,
    )
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            txt = f.read()
    except Exception:
        txt = None
    try:
        os.remove(ruta)
    except Exception:
        pass
    return txt


def main():
    local = (LOCAL_TEAM or "").strip()
    visitante = (VISITOR_TEAM or "").strip()
    if not local or not visitante:
        print("Debes definir LOCAL_TEAM y VISITOR_TEAM en el script.")
        return

    session = _get_session()
    try:
        resp = session.get(HOME_URL, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        print(f"Error al cargar portada: {exc}")
        return
    if resp.status_code != 200:
        print(f"No se pudo cargar la portada. Status: {resp.status_code}")
        return

    match_id = _buscar_partido_id(resp.text, local, visitante)
    if not match_id:
        print("No se encontro el partido en la portada.")
        return

    h2h_url = H2H_URL_TEMPLATE.format(match_id=match_id)
    try:
        h2h_resp = session.get(h2h_url, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        print(f"Error al cargar H2H: {exc}")
        return
    if h2h_resp.status_code != 200:
        print(f"No se pudo cargar H2H. Status: {h2h_resp.status_code}")
        return

    enlaces_local = _extraer_enlaces_h2h(h2h_resp.text, local, MAX_PARTIDOS)
    enlaces_visitante = _extraer_enlaces_h2h(h2h_resp.text, visitante, MAX_PARTIDOS)
    enlaces_enfrentamientos = _extraer_enlaces_enfrentamientos(h2h_resp.text, MAX_PARTIDOS)

    if not enlaces_local or not enlaces_visitante:
        print("No se pudieron obtener enlaces de H2H.")
        return

    estadisticas_local = []
    for match_id in enlaces_local:
        est = extraer_estadisticas_partido(session, match_id, equipo_referencia=local)
        estadisticas_local.append(est)

    estadisticas_visitante = []
    for match_id in enlaces_visitante:
        est = extraer_estadisticas_partido(session, match_id, equipo_referencia=visitante)
        estadisticas_visitante.append(est)

    estadisticas_enfrentamientos = []
    for match_id in enlaces_enfrentamientos:
        est = extraer_estadisticas_partido(session, match_id, equipo_referencia=local)
        estadisticas_enfrentamientos.append(est)

    liga_url = _resolver_liga_url(LIGA)
    contexto_liga = obtener_contexto_footystats(session, liga_url, local, visitante)

    # Si se solicita modo inline, devolver texto por stdout sin dejar fichero
    inline = any(a in ("--inline", "-i") for a in sys.argv)
    if inline:
        txt = generar_informe_text(
            local,
            visitante,
            estadisticas_local,
            estadisticas_visitante,
            estadisticas_enfrentamientos,
            contexto_liga=contexto_liga,
        )
        if txt is None:
            print("Error generando informe en modo inline.")
        else:
            print(txt)
    else:
        ruta_informe = generar_informe_txt(
            local,
            visitante,
            estadisticas_local,
            estadisticas_visitante,
            estadisticas_enfrentamientos,
            contexto_liga=contexto_liga,
        )
        print(f"Informe guardado en: {ruta_informe}")


if __name__ == "__main__":
    main()
