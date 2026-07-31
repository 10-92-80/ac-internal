import requests, os, re
from datetime import date

# ═══════════════════════════════════════════════════════════════════════════
# ZOHO AUTH
# Cada ejecución pide un access_token nuevo usando el refresh_token guardado
# como secreto en GitHub Actions. El access_token caduca en ~1h, por eso se
# regenera en cada run en lugar de guardarlo.
# ═══════════════════════════════════════════════════════════════════════════

def get_access_token():
    r = requests.post("https://accounts.zoho.eu/oauth/v2/token", data={
        "grant_type":    "refresh_token",
        "client_id":     os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
    })
    data = r.json()
    print("Zoho response:", {k:v for k,v in data.items() if k != "access_token"})
    if "access_token" not in data:
        raise Exception(f"Error Zoho: {data}")
    return data["access_token"]


def get_all_deals(token):
    """
    Descarga TODOS los registros del módulo Deals (paginando de 200 en 200,
    que es el máximo por página de la API de Zoho).
    Importante: aquí no se filtra nada todavía, se trae todo en bruto.
    Solo se piden los 5 campos que realmente se usan luego, para no
    sobrecargar la respuesta.
    """
    records, page = [], 1
    while True:
        r = requests.get(
            "https://www.zohoapis.eu/crm/v2/Deals",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params={"fields": "Deal_Name,Stage,Account_Name,Responsable_Interno_del_Deal,Calidad_Deal",
                    "per_page": 200, "page": page}
        )
        data = r.json()
        if "data" not in data: break          # Zoho no devuelve "data" si algo falla o no hay más
        records += data["data"]
        if not data.get("info", {}).get("more_records"): break   # fin de la paginación
        page += 1
    return records


def get_all_agro(token):
    """
    Igual que get_all_deals() pero apuntando al módulo custom
    Deals_Pipeline_Agro. Los nombres de campo son distintos porque es un
    módulo custom, pero el patrón de datos (registro "matriz" DEAL VIVO +
    registros candidato) es idéntico al de Deals:
        Deal_Name        -> Name
        Stage             -> Fase
        Account_Name      -> Nombre_de_Empresa
        Responsable_Interno_del_Deal -> Responsable_Deal
    """
    records, page = [], 1
    while True:
        r = requests.get(
            "https://www.zohoapis.eu/crm/v2/Deals_Pipeline_Agro",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params={"fields": "Name,Fase,Nombre_de_Empresa,Responsable_Deal,Calidad_Deal",
                    "per_page": 200, "page": page}
        )
        data = r.json()
        if "data" not in data: break
        records += data["data"]
        if not data.get("info", {}).get("more_records"): break
        page += 1
    return records


# ═══════════════════════════════════════════════════════════════════════════
# CLASIFICACIÓN
# Aquí se define qué es "vivo", qué se descarta y en qué orden se pinta todo.
# ═══════════════════════════════════════════════════════════════════════════

# Fases que NO cuentan como "candidato activo" de un deal (cerradas,
# descartadas, en stand-by, etc). Un deal puede tener 10 registros de
# candidatos y si todos están en estas fases, se trata como "sin candidatos".
# NOTA: Deals y Agro usan a veces textos ligeramente distintos para el mismo
# estado (mayúsculas, acentos, o una palabra distinta). Como este set se
# comparte entre los dos módulos, aquí se incluyen TODAS las variantes que
# existen en cualquiera de los dos, aunque una variante concreta no exista
# en el otro módulo (no hace daño tener de más, pero sí lo hace tener de menos).
EXCLUDED_STAGES = {
    "Recámara","Recáma",                                          # Deals dice "Recámara", Agro dice "Recáma"
    "Stand by","Stand By",                                        # Deals dice "Stand by", Agro dice "Stand By"
    "Descartada/Perdida","Descartada en Ciego","Closed Lost","Closed Lost to Competition",
    "Nunca se presentó",
    "Análisis pero descartado por Albero","Analisis, pero descartado por Albero","Análisis, pero descartada por Albero",  # 3 variantes vistas entre Deals y Agro
    "No Interesante","Vendido a otro / Potencial comprador","Cerrada y facturada",
    "Cerrada y cobrada","Cerrada y no facturada","Comprado con un tercero","-"
}

# En Zoho, cada "deal" real (ej: "Proyecto Hiria") se representa con VARIOS
# registros dentro del módulo Deals:
#   - Un registro "matriz" cuyo Account_Name es uno de estos marcadores
#     especiales (p.ej. "DEAL VIVO"), que indica el ESTADO del deal.
#   - Uno o más registros "candidato", donde Account_Name es el nombre real
#     de la empresa/inversor y Stage es la fase de esa negociación concreta.
# Por eso, al construir la lista de candidatos de un deal, hay que EXCLUIR
# los registros cuyo Account_Name sea uno de estos marcadores (si no, el
# propio registro matriz aparecería como si fuera un "candidato").
STATE_MARKERS = {
    "DEAL VIVO","DEAL NO DISPONIBLE","DEAL NO INTERESANTE","Pte. Asignar Comprador",
    "DEAL STAND-BY","DEAL POTENCIAL","DEAL FUTURO","DEAL CERRADO POR ALBERO"
}

RESP_ORDER    = ["CCF","LCT","MGM","AHBV","SLR"]   # orden interno de responsables (AHBV ya no se pinta, pero se mantiene la clasificación)
CALIDAD_ORDER = {"1. Alta":0,"2. Media":1,"3. Baja":2,"4. Pendiente":3}   # para ordenar de mejor a peor calidad
CALIDAD_COLOR = {"1. Alta":"#4caf50","2. Media":"#fb8c00","3. Baja":"#e53935","4. Pendiente":"#9c27b0"}  # color del semáforo


def acct(r):
    """Devuelve el nombre de la cuenta (Account_Name) de un registro de Deals.
    Account_Name es un campo lookup, así que en la respuesta de la API llega
    como un diccionario {"name": ..., "id": ...} y no como texto plano."""
    a = r.get("Account_Name","")
    return a["name"] if isinstance(a, dict) else (a or "")


def ag_acct(r):
    """Lo mismo que acct(), pero para el módulo Agro, donde el campo
    equivalente se llama Nombre_de_Empresa en vez de Account_Name."""
    a = r.get("Nombre_de_Empresa","")
    return a["name"] if isinstance(a, dict) else (a or "")


def clean_resp(r):
    """Responsable_Interno_del_Deal puede venir como lista, como string
    suelto o como None según el registro. Esto lo normaliza siempre a lista
    para poder tratarlo igual en todos los casos."""
    v = r.get("Responsable_Interno_del_Deal") or []
    return v if isinstance(v, list) else [v]


def build_pipeline(records):
    """
    A partir de los registros en bruto del módulo Deals, construye:
      - by_resp:  dict {responsable: [lista de candidatos]}
      - sb:       lista de nombres de deals en Stand-By
      - fu:       lista de nombres de deals Potenciales/Futuros
      - total:    nº de deals vivos
      - con_cands: nº de deals vivos que SÍ tienen al menos un candidato
    """

    # PASO 1 — localizar los deals "vivos": el registro matriz de cada deal
    # tiene Account_Name == "DEAL VIVO". De ahí sacamos también el
    # responsable "por defecto" del deal (resp_matriz), que se usa como
    # fallback si algún candidato no tiene responsable asignado.
    vivos = {}
    for r in records:
        if acct(r) == "DEAL VIVO":
            d = r["Deal_Name"]
            if d and d not in vivos:
                rl = clean_resp(r)
                resp = rl[0] if rl and rl[0] in RESP_ORDER else "CCF"
                vivos[d] = {"resp_matriz": resp, "calidad": r.get("Calidad_Deal")}

    # PASO 2 — deals en Stand-By y Potenciales/Futuros. Estos se identifican
    # de otra forma: Stage == "-" (fase vacía) y Account_Name es el marcador
    # correspondiente. No entran en "vivos", son otra categoría aparte.
    sb, fu = [], []
    seen_sb, seen_fu = set(), set()
    for r in records:
        if r.get("Stage") == "-":
            a = acct(r); d = r["Deal_Name"]
            if a == "DEAL STAND-BY" and d not in seen_sb:
                sb.append(d); seen_sb.add(d)
            elif a in ("DEAL POTENCIAL","DEAL FUTURO") and d not in seen_fu:
                fu.append(d); seen_fu.add(d)

    # PASO 3 — para cada deal vivo, recopilar sus candidatos reales:
    # registros cuyo Account_Name NO sea un marcador de estado y cuyo Stage
    # no esté en la lista de fases excluidas (cerradas/descartadas/etc).
    deal_cands = {d: [] for d in vivos}
    for r in records:
        d = r["Deal_Name"]
        if d not in vivos: continue
        stage = r.get("Stage",""); a = acct(r)
        if stage in EXCLUDED_STAGES or a in STATE_MARKERS: continue
        rl = clean_resp(r)
        resp = rl[0] if rl and rl[0] in RESP_ORDER else vivos[d]["resp_matriz"]
        deal_cands[d].append({"empresa": a, "stage": stage, "resp": resp})

    # PASO 4 — repartir cada candidato en la columna de su responsable.
    # Si un deal vivo no tiene NINGÚN candidato activo, se pinta igualmente
    # una fila de aviso ("Pte. candidatos") bajo el responsable matriz, para
    # que no desaparezca del pipeline sin más.
    by_resp = {r: [] for r in RESP_ORDER}
    for d, meta in vivos.items():
        cands = deal_cands[d]
        if cands:
            for c in cands:
                by_resp[c["resp"]].append({"deal":d,"calidad":meta["calidad"],"stage":c["stage"],"empresa":c["empresa"],"warn":False})
        else:
            by_resp[meta["resp_matriz"]].append({"deal":d,"calidad":meta["calidad"],"stage":"Pte. candidatos","empresa":"","warn":True})

    # PASO 5 — ordenar cada columna: primero por calidad (Alta > Media >
    # Baja > Pendiente) y luego alfabéticamente por nombre de deal. Los
    # avisos ("warn") siempre van al final, sin importar su calidad.
    for r in RESP_ORDER:
        normal = [x for x in by_resp[r] if not x["warn"]]
        warns  = [x for x in by_resp[r] if x["warn"]]
        normal.sort(key=lambda x: (CALIDAD_ORDER.get(x["calidad"] or "",4), x["deal"]))
        by_resp[r] = normal + warns

    return by_resp, sb, fu, len(vivos), sum(1 for d in vivos if deal_cands[d])


def build_agro_pipeline(records):
    """
    Misma lógica que build_pipeline(), pero simplificada para el módulo
    Agro: aquí NO se separa por responsable, se devuelve una única lista
    plana con todos los candidatos de todos los deals vivos de Agro.
    """

    # localizar deals vivos de Agro (mismo patrón DEAL VIVO que en Deals)
    vivos = {}
    for r in records:
        if ag_acct(r) == "DEAL VIVO":
            d = r["Name"]
            if d and d not in vivos:
                vivos[d] = {"calidad": r.get("Calidad_Deal")}

    # candidatos reales de cada deal vivo (excluyendo marcadores y fases descartadas)
    deal_cands = {d: [] for d in vivos}
    for r in records:
        d = r["Name"]
        if d not in vivos: continue
        stage = r.get("Fase",""); a = ag_acct(r)
        if stage in EXCLUDED_STAGES or a in STATE_MARKERS: continue
        deal_cands[d].append({"empresa": a, "stage": stage})

    # aplanar en una sola lista (sin agrupar por responsable)
    agro_list = []
    for d, meta in vivos.items():
        cands = deal_cands[d]
        if cands:
            for c in cands:
                agro_list.append({"deal":d,"calidad":meta["calidad"],"stage":c["stage"],"empresa":c["empresa"],"warn":False})
        else:
            agro_list.append({"deal":d,"calidad":meta["calidad"],"stage":"Pte. candidatos","empresa":"","warn":True})

    # mismo criterio de orden: calidad, luego nombre, avisos al final
    normal = [x for x in agro_list if not x["warn"]]
    warns  = [x for x in agro_list if x["warn"]]
    normal.sort(key=lambda x: (CALIDAD_ORDER.get(x["calidad"] or "",4), x["deal"]))
    return normal + warns


# ═══════════════════════════════════════════════════════════════════════════
# HTML
# A partir de aquí ya no se toca la API de Zoho: solo se pinta en HTML lo
# que build_pipeline() y build_agro_pipeline() han calculado.
# ═══════════════════════════════════════════════════════════════════════════

def sem(cal, warn=False):
    """Genera el puntito de color (semáforo) según la calidad del deal.
    Si es un aviso ("warn"), siempre sale gris independientemente de la
    calidad guardada."""
    col = "#999999" if warn else CALIDAD_COLOR.get(cal or "", "#9c27b0")
    return f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{col};margin-right:4px;vertical-align:middle;flex-shrink:0"></span>'


def trunc(s, n):
    """Corta un texto a n caracteres y añade '…' si se ha recortado, para
    que las celdas de la tabla no se desborden."""
    s = s or ""
    return (s[:n]+"…") if len(s)>n else s


# Define el ancho de las 9 columnas de cada tabla (3 grupos de 3 columnas:
# Deal / Fase / Empresa), repetido igual en la tabla de arriba y la de abajo.
COLGROUP = """<colgroup>
  <col class="cd"><col class="cf"><col class="ce">
  <col class="cd"><col class="cf"><col class="ce">
  <col class="cd"><col class="cf"><col class="ce">
</colgroup>"""

# Paletas de color de las celdas de datos, una por bloque visual:
#   DEFAULT -> CCF / LCT / MGM / SLR (gris neutro, el de siempre)
#   BLUE    -> STAND-BY & FUTUROS
#   GREEN   -> AGRO
# "bg_even"/"bg_odd" son el rayado (zebra) de filas pares/impares;
# "warn_bg"/"warn_text" son el color de las filas de aviso ("Pte. candidatos"),
# que se mantiene igual (ámbar) en todos los bloques para que se reconozca
# siempre como "aviso" sin importar el color del grupo.
DEFAULT_PALETTE = {"bg_even":"#f5f4f0","bg_odd":"#ffffff","text":"#62635e","warn_bg":"#fffbf0","warn_text":"#b8860b"}
BLUE_PALETTE    = {"bg_even":"#e9eff9","bg_odd":"#ffffff","text":"#3a5a8c","warn_bg":"#fffbf0","warn_text":"#b8860b"}
GREEN_PALETTE   = {"bg_even":"#eaf5ea","bg_odd":"#ffffff","text":"#3f6b3f","warn_bg":"#fffbf0","warn_text":"#b8860b"}

# Colores de las cabeceras (fila de título "STAND-BY & FUTUROS" / "AGRO" y
# la subfila "Deal/Fase/Empresa"), a juego con las paletas de arriba.
# CCF/LCT/MGM/SLR no llevan acento -> mantienen el gris/dorado de siempre.
HEADER_BLUE  = {"rh_bg":"#3a5a8c","rh_text":"#e9eff9","sh_bg":"#6d8fc4","sh_text":"#f0f4fb"}
HEADER_GREEN = {"rh_bg":"#3f6b3f","rh_text":"#eaf5ea","sh_bg":"#6fa06f","sh_text":"#eef7ee"}


def item_tds(items, idx, palette=None):
    """
    Genera las 3 celdas (<td>) de la fila `idx` para una lista de candidatos
    (`items`), usando la paleta de color indicada. Si `idx` no tiene dato
    (la columna ya se quedó sin candidatos pero otra columna de la misma
    fila todavía tiene), se devuelven 3 celdas vacías.
    Esta función es la que reutilizan tanto resp_tds() (columnas por
    responsable) como el bloque AGRO (lista plana, sin responsable).
    """
    p = palette or DEFAULT_PALETTE
    if idx < len(items):
        item = items[idx]
        bg = p["warn_bg"] if item["warn"] else (p["bg_even"] if idx%2==0 else p["bg_odd"])
        col = p["warn_text"] if item["warn"] else p["text"]
        st = f'background:{bg};color:{col};'
        return (
            f'<td style="{st}"><div class="dc">{sem(item["calidad"],item["warn"])}<span class="dt2">{trunc(item["deal"],28)}</span></div></td>',
            f'<td style="{st}">{trunc(item["stage"],15)}</td>',
            f'<td style="{st}">{trunc(item["empresa"],18)}</td>'
        )
    return "<td></td>","<td></td>","<td></td>"


def resp_tds(by_resp, r, idx):
    """Envoltorio de item_tds() para las columnas por responsable
    (CCF/LCT/MGM/SLR), siempre con la paleta gris por defecto."""
    return item_tds(by_resp[r], idx)


def sbfu_tds(sb, fu, idx, palette=None):
    """Genera las celdas del bloque Stand-By / Futuros. A diferencia de
    item_tds(), aquí cada celda es solo un nombre de deal (no hay
    Fase/Empresa), así que no usa sem() ni el semáforo de calidad."""
    p = palette or DEFAULT_PALETTE
    bg = p["bg_even"] if idx%2==0 else p["bg_odd"]
    s = f'<td style="background:{bg};color:{p["text"]};">{trunc(sb[idx],26)}</td>' if idx<len(sb) else f'<td style="background:{bg}"></td>'
    f = f'<td style="background:{bg};color:{p["text"]};">{trunc(fu[idx],26)}</td>' if idx<len(fu) else f'<td style="background:{bg}"></td>'
    return s, f, f'<td style="background:{bg}"></td>'


def build_html(by_resp, sb, fu, total, con_cands, agro_list):
    """
    Monta el documento HTML completo: cabecera + tabla superior
    (CCF/LCT/MGM) + tabla inferior (SLR / Stand-By&Futuros / Agro) + pie.
    Devuelve el HTML como string; quien lo llama se encarga de guardarlo.
    """
    today    = date.today()
    date_str = today.strftime("%d/%m/%Y")

    # nº de filas que necesita cada tabla = la columna más larga de ese bloque
    max_top = max(len(by_resp[r]) for r in ["CCF","LCT","MGM"])
    max_bot = max(len(by_resp["SLR"]), len(sb), len(fu), len(agro_list))

    def thead(lbls, subs, accents=None):
        """
        Genera las 2 filas de cabecera de una tabla:
          fila 1: nombre del grupo (colspan=3), ej. "AGRO"
          fila 2: nombre de cada subcolumna, ej. "Deal"/"Fase"/"Empresa"
        `accents` permite pintar un grupo con otro color (ver HEADER_BLUE /
        HEADER_GREEN); si es None para ese grupo, usa el gris/dorado normal.
        """
        accents = accents or [None]*len(lbls)
        h = "<thead><tr>"
        for i,l in enumerate(lbls):
            sep = "border-right:2px solid #eebb63;" if i<2 else ""   # separador dorado entre grupos (menos tras el último)
            acc = accents[i]
            rh_style = sep + (f'background:{acc["rh_bg"]};color:{acc["rh_text"]};' if acc else "")
            h += f'<th colspan="3" class="rh" style="{rh_style}">{l}</th>'
        h += "</tr><tr>"
        for i,(s1,s2,s3) in enumerate(subs):
            sep = " csep" if i<2 else ""   # separador fino gris entre grupos
            acc = accents[i]
            sh_style = f'background:{acc["sh_bg"]};color:{acc["sh_text"]};' if acc else ""
            h += f'<th class="sh" style="{sh_style}">{s1}</th><th class="sh" style="{sh_style}">{s2}</th><th class="sh{sep}" style="{sh_style}">{s3}</th>'
        return h + "</tr></thead>"

    # ── Cabecera del documento + estilos CSS + pantalla de login ───────────
    # El login es solo una contraseña comprobada en JS (client-side); no hay
    # backend real, es simplemente para que no cualquiera con el link vea
    # los datos. Se recuerda con sessionStorage mientras la pestaña esté abierta.
    H = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width">
<title>Pipeline Albero Capital</title>
<style>
@page{{size:A4 landscape;margin:8mm}}
*{{box-sizing:border-box;margin:0;padding:0;font-family:Arial,sans-serif}}
body{{width:277mm;font-size:8px;background:#fff;padding:4px}}
@media print{{
  *{{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
  col.cd{{width:37mm}}col.cf{{width:23mm}}col.ce{{width:32mm}}
  #login-overlay{{display:none!important}}
}}
#login-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;background:#62635e;display:flex;align-items:center;justify-content:center;z-index:9999}}
#login-box{{background:#fff;padding:32px 40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,0.2);min-width:280px}}
#login-box .logo{{font-size:18px;font-weight:bold;color:#eebb63;background:#62635e;padding:6px 16px;letter-spacing:1px;display:inline-block;margin-bottom:20px}}
#login-box input{{width:100%;padding:8px 10px;font-size:13px;border:1px solid #d9d8d2;margin-bottom:12px;outline:none;color:#62635e}}
#login-box button{{width:100%;padding:8px;background:#62635e;color:#eebb63;font-size:13px;font-weight:bold;border:none;cursor:pointer;letter-spacing:1px}}
#login-box button:hover{{background:#4a4b47}}
#login-error{{color:#e53935;font-size:11px;margin-top:6px;display:none}}
#content{{display:none}}
.hdr{{display:flex;justify-content:space-between;align-items:center;border-bottom:1.5px solid #eebb63;margin-bottom:3px;padding-bottom:2px}}
.brand{{font-size:13px;font-weight:bold;color:#eebb63;background:#62635e;padding:3px 9px;letter-spacing:1px}}
.sub{{font-size:8px;color:#62635e;margin-bottom:3px}}
.sep{{height:3px;background:#eebb63;margin:4px 0;opacity:0.35}}
table{{border-collapse:collapse;table-layout:fixed;width:100%}}
.rh{{background:#62635e;color:#eebb63;font-size:8px;font-weight:bold;text-align:center;padding:2px 0}}
.sh{{background:#82827c;color:#f5f4f0;font-size:7px;font-weight:bold;height:11px;line-height:11px;padding:0 2px;white-space:nowrap;overflow:hidden}}
td{{height:11px;line-height:11px;font-size:8px;padding:0 3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-bottom:1px solid #d9d8d2;color:#62635e;vertical-align:middle}}
.dc{{display:flex;align-items:center;overflow:hidden}}
.dt2{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.csep{{border-right:2px solid #d9d8d2}}
.ft{{font-size:7px;color:#82827c;text-align:center;margin-top:3px;border-top:1px solid #d9d8d2;padding-top:2px}}
</style>
<script>
function checkPassword(){{
  if(document.getElementById('pwd').value==='Albero109280'){{
    document.getElementById('login-overlay').style.display='none';
    document.getElementById('content').style.display='block';
    sessionStorage.setItem('albero_auth','1');
  }}else{{
    document.getElementById('login-error').style.display='block';
  }}
}}
function checkEnter(e){{if(e.key==='Enter')checkPassword();}}
window.onload=function(){{
  if(sessionStorage.getItem('albero_auth')==='1'){{
    document.getElementById('login-overlay').style.display='none';
    document.getElementById('content').style.display='block';
  }}
}};
</script>
</head><body>
<div id="login-overlay">
  <div id="login-box">
    <div class="logo">ALBERO CAPITAL</div>
    <div style="font-size:12px;color:#82827c;margin-bottom:16px;">Pipeline &mdash; Acceso restringido</div>
    <input type="password" id="pwd" placeholder="Contraseña" onkeypress="checkEnter(event)" autofocus>
    <button onclick="checkPassword()">ENTRAR</button>
    <div id="login-error">Contraseña incorrecta</div>
  </div>
</div>
<div id="content">
<div class="hdr"><div class="brand">ALBERO CAPITAL</div><span style="font-size:8px;color:#82827c">{date_str}</span></div>
<div class="sub">Deals/Pipeline &mdash; Actual Status &nbsp;&middot;&nbsp; Deals vivos: <strong>{total}</strong> &nbsp;|&nbsp; Con candidatos: <strong>{con_cands}</strong></div>
"""

    # ── TABLA SUPERIOR: CCF | LCT | MGM ─────────────────────────────────────
    # Los 3 responsables "principales", siempre con la paleta gris por defecto.
    H += f"<table>{COLGROUP}"
    H += thead(["CCF","LCT","MGM"],[("Deal","Fase","Empresa")]*3)
    H += "<tbody>\n"
    for idx in range(max_top):
        H += "<tr>"
        for ci,r in enumerate(["CCF","LCT","MGM"]):
            t1,t2,t3 = resp_tds(by_resp, r, idx)
            if ci < 2: t3 = re.sub(r"^<td","<td class=\"csep\"",t3)   # separador entre CCF|LCT y LCT|MGM (no tras MGM)
            H += t1+t2+t3
        H += "</tr>\n"
    H += "</tbody></table>\n"

    H += '<div class="sep"></div>\n'   # línea dorada fina entre las 2 tablas

    # ── TABLA INFERIOR: SLR | STAND-BY & FUTUROS | AGRO ─────────────────────
    # SLR usa la paleta gris (igual que CCF/LCT/MGM). Los otros 2 bloques
    # llevan su propio color (azul / verde) tanto en cabecera como en celdas,
    # para diferenciarlos visualmente de los 4 responsables "principales".
    H += f"<table>{COLGROUP}"
    H += thead(["SLR","STAND-BY &amp; FUTUROS","AGRO"],
               [("Deal","Fase","Empresa"),("Stand-By","Futuro",""),("Deal","Fase","Empresa")],
               accents=[None, HEADER_BLUE, HEADER_GREEN])
    H += "<tbody>\n"
    for idx in range(max_bot):
        H += "<tr>"
        t1,t2,t3 = resp_tds(by_resp, "SLR", idx)
        t3 = re.sub(r"^<td","<td class=\"csep\"",t3)                 # separador entre SLR y Stand-By&Futuros
        H += t1+t2+t3
        s,f,v = sbfu_tds(sb, fu, idx, palette=BLUE_PALETTE)
        v = re.sub(r"^<td","<td class=\"csep\"",v)                   # separador entre Stand-By&Futuros y Agro
        H += s+f+v
        a1,a2,a3 = item_tds(agro_list, idx, palette=GREEN_PALETTE)
        H += a1+a2+a3
        H += "</tr>\n"
    H += "</tbody></table>\n"

    H += f'<div class="ft">Albero Capital &nbsp;&middot;&nbsp; Datos en tiempo real desde Zoho CRM &nbsp;&middot;&nbsp; {date_str}</div>\n'
    H += "</div></body></html>"
    return H


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# Esto es lo que ejecuta GitHub Actions (update.yml) 3 veces al día:
# 1) pide token, 2) descarga datos de ambos módulos, 3) los clasifica,
# 4) genera el HTML y 5) lo escribe en docs/index.html para GitHub Pages.
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Obteniendo token...")
    token = get_access_token()

    print("Descargando deals...")
    records = get_all_deals(token)
    print(f"Total registros: {len(records)}")

    print("Descargando deals Agro...")
    agro_records = get_all_agro(token)
    print(f"Total registros Agro: {len(agro_records)}")

    by_resp, sb, fu, total, con_cands = build_pipeline(records)
    agro_list = build_agro_pipeline(agro_records)
    print(f"Deals vivos: {total} | Con candidatos: {con_cands} | Deals vivos Agro: {len(agro_list)}")

    html = build_html(by_resp, sb, fu, total, con_cands, agro_list)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html","w",encoding="utf-8") as f:
        f.write(html)
    print("OK — docs/index.html generado")
