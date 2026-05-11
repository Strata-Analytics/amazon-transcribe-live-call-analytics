import boto3
import json
import os
import re
import time
from decimal import Decimal
from boto3.dynamodb.conditions import Key

bedrock        = boto3.client('bedrock-runtime',       region_name='us-east-1')
bedrock_agent  = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
dynamodb       = boto3.resource('dynamodb',            region_name='us-east-1')

DYNAMODB_TABLE_NAME  = os.environ.get('DYNAMODB_TABLE_NAME', '')
TABLA_PLANES    = os.environ.get('TABLA_PLANES',   'lca-poc-copilot-telco-planes')
TABLA_CLIENTES  = os.environ.get('TABLA_CLIENTES', 'lca-poc-copilot-telco-clientes')
TABLA_OFERTAS   = os.environ.get('TABLA_OFERTAS',  'lca-poc-copilot-telco-ofertas')

KNOWLEDGE_BASE_ID    = os.environ.get('KNOWLEDGE_BASE_ID', '')
MODEL_ID             = os.environ.get('MODEL_ID', 'us.anthropic.claude-haiku-4-5-20251001-v1:0')
MAX_CONTEXT_SEGMENTS = 10
CACHE_TTL_SECONDS    = 300  # 5 min — prevents stale profiles across back-to-back demo calls

VALID_ACTIONS = {
    'OPORTUNIDAD_VENTA', 'UPSELL', 'INFORMACION_ADICIONAL', 'RETENCIÓN', 'MANEJO_OBJECION',
    'OFERTA_ESPECIAL', 'ESCALACIÓN', 'SOPORTE', 'CIERRE', 'ESPERAR'
}

# Module-level caches: key → (item_dict, timestamp)
_cliente_cache: dict = {}
_plan_cache:    dict = {}
_oferta_cache:  dict = {}


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _ddb_to_native(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _ddb_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ddb_to_native(i) for i in obj]
    return obj


def _normalize_phone(phone: str) -> str:
    return re.sub(r'[\s\+\-\(\)]', '', phone)


def get_cliente(telefono: str) -> dict:
    key    = _normalize_phone(telefono)
    cached = _cliente_cache.get(key)
    if cached and time.time() - cached[1] < CACHE_TTL_SECONDS:
        print(f"cliente cache HIT: {key}")
        return cached[0]
    try:
        table = dynamodb.Table(TABLA_CLIENTES)
        resp  = table.get_item(Key={'telefono': key})
        item  = _ddb_to_native(resp.get('Item', {}))
        print(f"cliente DDB: {key} → nombre={item.get('nombre','?')}")
        _cliente_cache[key] = (item, time.time())
        return item
    except Exception as e:
        print(f"DDB get_cliente error: {e}")
        return {}


def get_cliente_by_nombre(nombre: str) -> dict:
    """Scan by first name — demo only. In production use a GSI on 'nombre'."""
    first = nombre.strip().split()[0].title() if nombre.strip() else ''
    if not first:
        return {}
    try:
        table = dynamodb.Table(TABLA_CLIENTES)
        resp  = table.scan(
            FilterExpression='contains(#n, :v)',
            ExpressionAttributeNames={'#n': 'nombre'},
            ExpressionAttributeValues={':v': first}
        )
        items = [_ddb_to_native(i) for i in resp.get('Items', [])]
        if items:
            print(f"cliente scan '{first}' → {items[0].get('nombre','?')}")
            return items[0]
    except Exception as e:
        print(f"DDB scan by nombre error: {e}")
    return {}


def get_plan(plan_id: str) -> dict:
    cached = _plan_cache.get(plan_id)
    if cached and time.time() - cached[1] < CACHE_TTL_SECONDS:
        return cached[0]
    try:
        table = dynamodb.Table(TABLA_PLANES)
        resp  = table.get_item(Key={'plan_id': plan_id})
        item  = _ddb_to_native(resp.get('Item', {}))
        print(f"plan DDB: {plan_id} → precio={item.get('precio','?')} datos_gb={item.get('datos_gb','?')}")
        _plan_cache[plan_id] = (item, time.time())
        return item
    except Exception as e:
        print(f"DDB get_plan error: {e}")
        return {}


def get_oferta(oferta_id: str) -> dict:
    cached = _oferta_cache.get(oferta_id)
    if cached and time.time() - cached[1] < CACHE_TTL_SECONDS:
        return cached[0]
    try:
        table = dynamodb.Table(TABLA_OFERTAS)
        resp  = table.get_item(Key={'oferta_id': oferta_id})
        item  = _ddb_to_native(resp.get('Item', {}))
        _oferta_cache[oferta_id] = (item, time.time())
        return item
    except Exception as e:
        print(f"DDB get_oferta error: {e}")
        return {}


def get_bundle_config() -> dict:
    return get_plan('CONFIG#BUNDLE')


# ---------------------------------------------------------------------------
# Client identification — phone + name cross-validation
# ---------------------------------------------------------------------------

def extract_name_from_context(transcript: str, context_text: str) -> str:
    """
    Extract first + last name from caller self-introductions in current or prior segments.
    Returns title-cased string, e.g. 'Roberto Hernandez', or '' if not found.
    """
    full = f"{context_text}\n{transcript}".lower()
    patterns = [
        r"mi nombre es ([a-záéíóúüñ]+ [a-záéíóúüñ]+)",
        r"me llamo ([a-záéíóúüñ]+ [a-záéíóúüñ]+)",
        r"habla ([a-záéíóúüñ]+ [a-záéíóúüñ]+)",
        r"le habla ([a-záéíóúüñ]+ [a-záéíóúüñ]+)",
        r"soy ([a-záéíóúüñ]+ [a-záéíóúüñ]+)",
    ]
    for pat in patterns:
        m = re.search(pat, full)
        if m:
            return m.group(1).title()
    return ''


def resolve_cliente(event: dict, transcript: str, context_text: str,
                    call_id: str, table_name: str, dynamodb_pk: str) -> tuple:
    """
    Returns (cliente_dict, confirmed: bool).

    confirmed=True  — name in call matches phone profile, or found via name scan.
    confirmed=False — phone profile found but client hasn't said their name yet.
                      Profile is injected with a warning so the model treats it as a hint.

    If phone profile name doesn't match spoken name, try name scan.
    If name scan also fails, return empty — better no profile than wrong profile.
    """
    phone = get_customer_phone_from_event(event)
    if not phone:
        phone = get_phone_from_lca_dynamodb(call_id, table_name, dynamodb_pk)
    print(f"phone resolved: '{phone}'")

    cliente_by_phone  = get_cliente(phone) if phone else {}
    nombre_mencionado = extract_name_from_context(transcript, context_text)
    print(f"nombre mencionado: '{nombre_mencionado}'")

    if not cliente_by_phone:
        if nombre_mencionado:
            c = get_cliente_by_nombre(nombre_mencionado)
            return (c, True) if c else ({}, False)
        return {}, False

    if not nombre_mencionado:
        # Phone matched, client hasn't said name yet — unconfirmed hint
        return cliente_by_phone, False

    # Cross-validate name vs phone profile
    nombre_perfil = cliente_by_phone.get('nombre', '').lower()
    if any(p in nombre_perfil for p in nombre_mencionado.lower().split()):
        return cliente_by_phone, True

    # Mismatch — try name scan before giving up
    print(f"nombre '{nombre_mencionado}' != perfil '{nombre_perfil}', buscando por nombre")
    c = get_cliente_by_nombre(nombre_mencionado)
    if c:
        return c, True

    print("no se encontró perfil por nombre, operando sin perfil")
    return {}, False


# ---------------------------------------------------------------------------
# Phone extraction
# ---------------------------------------------------------------------------

def get_customer_phone_from_event(event: dict) -> str:
    tsa = event.get('transcript_segment_args', {})
    raw = (
        event.get('CustomerPhoneNumber') or
        event.get('callerPhoneNumber')   or
        tsa.get('CustomerPhoneNumber')   or
        tsa.get('callerPhoneNumber')     or
        tsa.get('CallerPhoneNumber')     or ''
    )
    return _normalize_phone(raw) if raw else ''


def get_phone_from_lca_dynamodb(call_id: str, table_name: str, pk_override: str = '') -> str:
    name = table_name or DYNAMODB_TABLE_NAME
    if not name or not call_id:
        return ''
    pk = pk_override or f'c#{call_id}'
    try:
        table = dynamodb.Table(name)
        resp  = table.query(KeyConditionExpression=Key('PK').eq(pk), Limit=10)
        items = resp.get('Items', [])
        print(f"phone lookup PK={pk} items={len(items)}")
        for item in items:
            raw = (item.get('CustomerPhoneNumber') or
                   item.get('callerPhoneNumber')   or
                   item.get('CallerPhoneNumber')   or '')
            if raw:
                return _normalize_phone(raw)
        print("phone lookup: no phone field found")
    except Exception as e:
        print(f"LCA phone lookup error: {e}")
    return ''


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

def compute_insights(cliente: dict, plan_data: dict) -> dict:
    insights = {}
    consumo  = cliente.get('consumo_promedio_gb')
    limite   = cliente.get('limite_plan_gb')

    if limite is None and plan_data:
        gb     = plan_data.get('datos_gb')
        limite = gb if isinstance(gb, (int, float)) else None

    if not (consumo and limite and consumo > limite):
        return insights

    gap_gb         = consumo - limite
    gasto_paquetes = cliente.get('gasto_paquetes_mensual')
    if gasto_paquetes is None:
        pkg_cfg        = get_plan('CONFIG#PAQUETES')
        precio_gb      = pkg_cfg.get('precio_paquete_gb', 30) if pkg_cfg else 30
        gasto_paquetes = gap_gb * precio_gb

    upgrade_id     = plan_data.get('upgrade')
    upgrade_data   = get_plan(upgrade_id) if upgrade_id else {}
    upgrade_precio = upgrade_data.get('precio')
    plan_precio    = plan_data.get('precio', 0)

    if upgrade_precio:
        delta = upgrade_precio - plan_precio
        insights['data_gap'] = {
            'limite_gb':      limite,
            'consumo_gb':     consumo,
            'gap_gb':         gap_gb,
            'extra_cost_est': gasto_paquetes,
            'upgrade_id':     upgrade_id,
            'upgrade_precio': upgrade_precio,
            'upgrade_gb':     upgrade_data.get('datos_gb'),
            'upgrade_delta':  delta,
            'net_saving':     gasto_paquetes - delta,
        }
    return insights


def compute_retencion_oferta(cliente: dict, plan_data: dict) -> str:
    antiguedad  = cliente.get('antiguedad_meses', 0)
    # FIX: fallback to cliente when plan_data doesn't carry plan_id key
    plan_id     = plan_data.get('plan_id') or cliente.get('plan_movil_actual', '')
    plan_precio = plan_data.get('precio', 0)
    upgrade_id  = plan_data.get('upgrade')
    upgrade_data   = get_plan(upgrade_id) if upgrade_id else {}
    upgrade_precio = upgrade_data.get('precio', 0)
    upgrade_gb     = upgrade_data.get('datos_gb')

    lines = []

    ret = get_oferta('RET-A')
    if ret:
        desc = ret.get('descuento_pct', 20)
        dur  = ret.get('duracion_meses', 3)
        lines.append(
            f"RET-A (ofrecer primero): {desc}% dto en plan actual "
            f"({plan_id} ${plan_precio}) → ${round(plan_precio * (1 - desc/100))}/mes por {dur} meses"
        )

    if upgrade_id and upgrade_precio and antiguedad >= 12:
        ret = get_oferta('RET-B')
        if ret:
            dur    = ret.get('duracion_meses', 6)
            gb_str = f", {upgrade_gb}GB" if upgrade_gb else ''
            lines.append(
                f"RET-B (si rechaza RET-A): upgrade gratuito a {upgrade_id} "
                f"(${upgrade_precio}{gb_str}) por {dur} meses"
            )

    if upgrade_id and upgrade_precio and (antiguedad >= 24 or plan_precio >= 500):
        ret = get_oferta('RET-C')
        if ret:
            desc   = ret.get('descuento_pct', 30)
            dur    = ret.get('duracion_meses', 3)
            gb_str = f", {upgrade_gb}GB" if upgrade_gb else ''
            lines.append(
                f"RET-C (último recurso, NO ofrecer directo): {upgrade_id} "
                f"(${upgrade_precio}{gb_str}) con {desc}% dto → "
                f"${round(upgrade_precio * (1 - desc/100))}/mes por {dur} meses"
            )

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Profile section
# ---------------------------------------------------------------------------

def build_profile_section(cliente: dict, plan_data: dict, insights: dict,
                           confirmado: bool = True) -> str:
    if not cliente:
        return ''

    lines       = []
    plan_id     = cliente.get('plan_movil_actual', '')
    plan_precio = plan_data.get('precio', cliente.get('precio_movil_actual', '?'))
    consumo     = cliente.get('consumo_promedio_gb')
    antiguedad  = cliente.get('antiguedad_meses')
    pagos       = cliente.get('pagos_atrasados', 0)

    lines.append(f"nombre: {cliente.get('nombre', 'desconocido')}")
    if plan_id:
        lines.append(f"plan_actual: {plan_id} (${plan_precio}/mes) — NO ofrecer este mismo plan")
    if consumo is not None:
        lines.append(f"consumo_promedio: {consumo}GB/mes")
    if antiguedad is not None:
        lines.append(f"antigüedad: {antiguedad} meses")

    if cliente.get('internet_hogar'):
        proveedor = cliente.get('proveedor_internet_hogar', '')
        precio_ih = cliente.get('precio_internet_hogar_actual', '')
        extra     = f" con {proveedor} (${precio_ih}/mes)" if proveedor else ''
        lines.append(f"internet_hogar: SÍ{extra} — NO ofrecer planes HOG ni bundle")
    else:
        lines.append("internet_hogar: NO — oportunidad CROSS_SELL bundle")

    if cliente.get('viaja_frecuente_eeuu'):
        lines.append("viaja_frecuente_eeuu: SÍ — oportunidad UPSELL a MOV-PRO (roaming incluido)")

    if cliente.get('grupo_familiar'):
        lines.append("grupo_familiar: SÍ — oportunidad CROSS_SELL plan familiar")

    if pagos > 0:
        lines.append(f"PAGOS ATRASADOS: {pagos} — NO vender hasta resolver")

    gap = insights.get('data_gap')
    if gap:
        costo_real    = plan_precio + gap['extra_cost_est']
        delta_vs_real = gap['upgrade_precio'] - costo_real
        if delta_vs_real <= 0:
            net_str = f"ahorro ${abs(delta_vs_real)}/mes vs su gasto real (${costo_real}/mes con paquetes)"
        else:
            net_str = f"solo ${delta_vs_real}/mes más vs su gasto real de ${costo_real}/mes (plan + paquetes)"
        lines.append(
            f"GAP DE CONSUMO: usa {gap['consumo_gb']}GB pero plan incluye {gap['limite_gb']}GB → "
            f"gasta ~${gap['extra_cost_est']}/mes en paquetes extra. "
            f"Upgrade a {gap['upgrade_id']} (${gap['upgrade_precio']}) = {net_str}."
        )

    if not confirmado:
        lines.append(
            "⚠ PERFIL NO CONFIRMADO: el cliente aún no dijo su nombre o no coincidió con el "
            "teléfono registrado. Usar estos datos como referencia orientativa. Si el cliente "
            "menciona algo distinto (otro plan, otra situación), priorizar lo que dice el cliente."
        )

    return "DATOS DEL CLIENTE:\n" + '\n'.join(f"• {l}" for l in lines)


# ---------------------------------------------------------------------------
# Call context
# ---------------------------------------------------------------------------

def get_call_context(dynamodb_pk: str, current_segment_id: str, table_name: str) -> str:
    name = table_name or DYNAMODB_TABLE_NAME
    if not name or not dynamodb_pk:
        return ''
    try:
        table = dynamodb.Table(name)
        resp  = table.query(
            KeyConditionExpression=Key('PK').eq(dynamodb_pk),
            ScanIndexForward=False,
            Limit=MAX_CONTEXT_SEGMENTS * 3
        )
        segments = []
        for item in resp.get('Items', []):
            if item.get('Channel') in ('CALLER', 'AGENT', 'AGENT_ASSISTANT') and \
               item.get('SegmentId') != current_segment_id and item.get('Transcript'):
                ch        = item['Channel']
                role      = 'Cliente' if ch == 'CALLER' else ('Agente' if ch == 'AGENT' else 'Copilot')
                sentiment = item.get('Sentiment', '')
                s         = f" [{sentiment}]" if sentiment and sentiment not in ('NEUTRAL', '') else ''
                segments.append(f"{role}{s}: {item['Transcript']}")
        segments.reverse()
        caller_count, filtered = 0, []
        for seg in segments:
            filtered.append(seg)
            if seg.startswith('Cliente'):
                caller_count += 1
            if caller_count >= MAX_CONTEXT_SEGMENTS:
                break
        return '\n'.join(filtered)
    except Exception as e:
        print(f"DynamoDB context error: {e}")
        return ''


# ---------------------------------------------------------------------------
# Knowledge Base — single query per invocation
# ---------------------------------------------------------------------------

def query_kb(query: str, n: int = 2) -> str:
    if not KNOWLEDGE_BASE_ID:
        return ''
    try:
        resp = bedrock_agent.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': query},
            retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults': n}}
        )
        return '\n\n'.join(
            r.get('content', {}).get('text', '')
            for r in resp.get('retrievalResults', [])
            if r.get('content', {}).get('text', '')
        )
    except Exception as e:
        print(f"KB error: {e}")
        return ''


def get_relevant_scripts(transcript: str, cliente: dict) -> str:
    """Single KB query — highest-priority signal wins. Reduces latency."""
    if not KNOWLEDGE_BASE_ID:
        return ''

    tl             = transcript.lower()
    plan_id        = cliente.get('plan_movil_actual', '')
    internet_hogar = cliente.get('internet_hogar', False)

    if any(w in tl for w in ["cancelar", "baja", "portarme", "otra empresa",
                               "movistar", "at&t", "telcel", "competencia", "me voy"]):
        query, label = "script retención cancelar qué decirle al cliente que quiere cancelar", "SCRIPTS RETENCIÓN"
    elif any(w in tl for w in ["familiar", "familia", "esposo", "esposa", "hijo",
                                 "líneas", "lineas", "varias líneas"]):
        query, label = "plan familiar múltiples líneas argumento cross-sell familia", "ARGUMENTO PLAN FAMILIAR"
    elif any(w in tl for w in ["caro", "costoso", "no me alcanza", "más barato",
                                 "descuento", "sale muy"]):
        query, label = "manejo objeción precio caro argumentos valor", "MANEJO OBJECIÓN PRECIO"
    elif any(w in tl for w in ["gigas", "datos", "paquetes", "me quedé",
                                 "roaming", "viaj", "estados unidos", "eeuu"]):
        query, label = f"argumentos upsell más datos plan superior {plan_id}", "ARGUMENTOS UPSELL"
    elif not internet_hogar and any(w in tl for w in ["internet", "hogar", "casa",
                                                        "telmex", "izzi", "totalplay",
                                                        "megacable", "fibra", "wifi"]):
        query, label = "bundle internet hogar móvil ahorro argumento cross-sell", "ARGUMENTO BUNDLE"
    else:
        return ''

    kb = query_kb(query, n=2)
    return f"{label}:\n{kb}" if kb else ''


# ---------------------------------------------------------------------------
# Pricing context
# ---------------------------------------------------------------------------

def build_pricing_context(cliente: dict, plan_data: dict, insights: dict, tl: str) -> str:
    lines       = []
    plan_id     = cliente.get('plan_movil_actual', '')
    plan_precio = plan_data.get('precio', 0)
    upgrade_id  = plan_data.get('upgrade')
    gap         = insights.get('data_gap')

    price_signals = any(w in tl for w in [
        "caro", "costoso", "descuento", "más barato", "cuánto", "precio", "diferencia"
    ])

    if price_signals and plan_precio:
        upgrade_data = get_plan(upgrade_id) if upgrade_id else {}
        up_precio    = upgrade_data.get('precio', 0)
        up_gb        = upgrade_data.get('datos_gb')
        gb_str       = f", {up_gb}GB" if up_gb else ''

        if gap and up_precio:
            costo_real = plan_precio + gap['extra_cost_est']
            lines.append("TABLA DE COSTOS (usar EXACTAMENTE estos números):")
            lines.append(f"  [A] Diferencia pura entre planes (meses SIN paquetes):")
            lines.append(f"      {upgrade_id} (${up_precio}{gb_str}) − {plan_id} (${plan_precio}) = ${up_precio - plan_precio}/mes más")
            lines.append(f"      → Si el cliente afirma '${up_precio - plan_precio} de diferencia', TIENE RAZÓN. No corregirle.")
            lines.append(f"  [B] Costo real actual (meses CON paquetes):")
            lines.append(f"      ${plan_precio} (plan) + ${gap['extra_cost_est']} (paquetes estimados) = ${costo_real}/mes")
            lines.append(f"      {upgrade_id} regular (${up_precio}{gb_str}): {up_precio - costo_real:+}/mes vs [B]")
            lines.append(f"      {upgrade_id} con 20% dto (${round(up_precio*0.80)}, 3 meses): {round(up_precio*0.80) - costo_real:+}/mes vs [B]")
            lines.append(f"      {upgrade_id} con 30% dto (${round(up_precio*0.70)}, 3 meses): {round(up_precio*0.70) - costo_real:+}/mes vs [B]")
            lines.append("  REGLA: Si el cliente dice que no siempre compra paquetes → presentar [A] y [B] como dos escenarios sin contradecirle.")
        else:
            lines.append(f"{plan_id} con 20% dto: ${round(plan_precio * 0.80)}/mes por 3 meses")
            if upgrade_id and up_precio:
                lines.append(f"Upgrade a {upgrade_id} (${up_precio}{gb_str}) gratis 6 meses (RET-B)")
                lines.append(f"{upgrade_id} con 30% dto: ${round(up_precio * 0.70)}/mes por 3 meses (RET-C)")

    if not cliente.get('internet_hogar'):
        if any(w in tl for w in ["internet", "hogar", "izzi", "telmex", "totalplay"]):
            bundle_cfg = get_bundle_config()
            desc_pct   = bundle_cfg.get('descuento_pct', 15) if bundle_cfg else 15
            proveedor  = cliente.get('proveedor_internet_hogar', '')
            precio_ih  = cliente.get('precio_internet_hogar_actual', 0)
            if plan_precio:
                hog        = get_plan('HOG-100')
                hog_precio = hog.get('precio', 499) if hog else 499
                total_sin  = plan_precio + hog_precio
                total_con  = round(total_sin * (1 - desc_pct / 100))
                ahorro     = total_sin - total_con
                competitor = f" (actualmente paga ${precio_ih}/mes con {proveedor})" if precio_ih and proveedor else ''
                lines.append(
                    f"Bundle {plan_id} + HOG-100{competitor}: "
                    f"${total_con}/mes en lugar de ${total_sin} — ahorro ${ahorro}/mes"
                )

    return '\n'.join(lines) if lines else ''


def build_familiar_context(cliente: dict, plan_data: dict, tl: str) -> str:
    if not any(w in tl for w in [
        "familiar", "familia", "esposo", "esposa", "hijo", "hija",
        "líneas", "lineas", "dos líneas", "varias líneas", "agregar línea"
    ]):
        return ''

    fam3        = get_plan('MOV-FAMILIAR-3')
    fam5        = get_plan('MOV-FAMILIAR-5')
    plan_id     = cliente.get('plan_movil_actual', 'MOV-BASIC')
    plan_precio = plan_data.get('precio', 199)
    basic       = get_plan('MOV-BASIC')
    plus        = get_plan('MOV-PLUS')

    lines = ["OPCIONES PLAN FAMILIAR (usar EXACTAMENTE estos datos, sin inventar):"]
    lines.append(f"• 2 planes individuales {plan_id}: 2×${plan_precio} = ${2*plan_precio}/mes")
    if basic and plus:
        lines.append(
            f"• 2 planes MOV-BASIC: ${2*basic.get('precio',199)}/mes | "
            f"2 planes MOV-PLUS: ${2*plus.get('precio',299)}/mes"
        )
    if fam3:
        p3, gb3, ah3 = fam3.get('precio',749), fam3.get('datos_gb_por_linea',15), fam3.get('ahorro_vs_individual_mxn',148)
        lines.append(f"• MOV-FAMILIAR-3: ${p3}/mes — 3 líneas, {gb3}GB POR LÍNEA (no compartidos). Ahorro real: ${ah3}/mes vs 3 planes MOV-PLUS individuales.")
    if fam5:
        p5, gb5, ah5 = fam5.get('precio',1099), fam5.get('datos_gb_por_linea',15), fam5.get('ahorro_vs_individual_mxn',396)
        lines.append(f"• MOV-FAMILIAR-5: ${p5}/mes — 5 líneas, {gb5}GB POR LÍNEA. Ahorro real: ${ah5}/mes vs 5 planes MOV-PLUS individuales.")
    lines.append("REGLA: No existe plan de 2 líneas. Para 2 personas → 2 planes individuales O MOV-FAMILIAR-3 con 1 línea extra disponible.")
    lines.append("PROHIBIDO: No inventar descuentos, no usar precios de retención en este contexto.")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres el copilot inteligente de un agente de contact center de telecomunicaciones de TelcoStrata.
Tu objetivo es analizar la transcripción en tiempo real y sugerir la siguiente mejor acción (Next Best Action).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLAS — LEER COMPLETO ANTES DE RESPONDER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. JSON PURO: Responde ÚNICAMENTE con un JSON válido. Sin markdown, sin texto adicional.

2. CATÁLOGO CERRADO — solo estos IDs, precios y GB existen:
   MOV-BASIC $199/5GB · MOV-PLUS $299/15GB · MOV-PRO $449/30GB · MOV-UNLIMITED $599/ilimitado
   MOV-FAMILIAR-3 $749 (3 líneas, 15GB c/u) · MOV-FAMILIAR-5 $1099 (5 líneas, 15GB c/u)
   HOG-50 $349 · HOG-100 $499 · HOG-300 $699 · HOG-GIGA $999
   PROHIBIDO: "MOV-ULTRA", "10GB en MOV-PLUS", "Plan Familiar Plus", cualquier plan no listado.

3. PRECIOS Y GB: usar SOLO los de DATOS DEL CLIENTE, TABLA DE COSTOS o el catálogo. Nunca inventar.

4. NOMBRE DEL CLIENTE: usar el nombre de DATOS DEL CLIENTE. NUNCA escribir "[Nombre]", "[nombre del cliente]" ni ningún placeholder.

5. PERFIL NO CONFIRMADO: si DATOS DEL CLIENTE incluye ":warning: PERFIL NO CONFIRMADO", tratar como referencia orientativa. Si el cliente menciona algo distinto, priorizar lo que dice el cliente.

6. NO OFRECER LO QUE YA TIENE: si plan_actual está en DATOS DEL CLIENTE, nunca recomendarlo.

7. NO OPORTUNIDAD_VENTA HOGAR si internet_hogar: SÍ en DATOS DEL CLIENTE.

8. ESPERAR obligatorio — sin excepciones:
   • Menos de 4 palabras: "sí", "no", "ok", "ajá", "um", letras sueltas
   • Saludos: "Hola", "Buenos días", "Buenas tardes"
   • Solo el nombre: "Mi nombre es Carlos Mendoza"
   • Frase incompleta — termina con: "porque", "y", "pero", "que", "um", "eh", "este", "entonces"

9. PAGOS ATRASADOS: si figura en DATOS DEL CLIENTE → SOPORTE siempre. No vender.

10. SOLICITUD EXPLÍCITA PRIMERO: si el cliente dijo claramente lo que quiere, responder ÚNICAMENTE a eso.

11. CONTEXTO DE LA LLAMADA: revisar SIEMPRE antes de decidir.
    • Si "Copilot:" ya ofreció RET-A → siguiente oferta es RET-B.
    • Si el cliente ya aceptó → CIERRE, no seguir vendiendo.
    • Si el cliente dijo "cancelar" en turno anterior → mantener contexto de RETENCIÓN.
    • Si el cliente ya rechazó una categoría de producto → NO volver a ofrecerla.

12. RETENCIÓN — JERARQUÍA ESTRICTA:
    • Orden: exploración → RET-A → RET-B → RET-C. Avanzar solo si el anterior fue rechazado explícitamente.
    • RET-C: último recurso. No ofrecer si RET-B no fue rechazado.
    • Descuentos RET son EXCLUSIVOS de retención. PROHIBIDO en UPSELL/OPORTUNIDAD_VENTA.

13. UPSELL CON TABLA DE COSTOS — dos escenarios:
    • [A] Diferencia pura entre planes (meses sin paquetes): upgrade_precio − plan_precio
    • [B] Vs costo real actual (plan + paquetes estimados)
    • Si el cliente afirma que la diferencia es [A], TIENE RAZÓN. No corregirle.
    • Si dice que no siempre compra paquetes → presentar [A] y [B] como opciones.
    • NUNCA mezclar precio con descuento + framing "solo $X más".

14. CIERRE — señales de compra (responder CIERRE, no seguir vendiendo):
    "lo quiero" · "me quedo con ese" · "me interesa" · "me convence" · "cómo lo activo"
    "cuándo entra en vigor" · "cómo puedo avanzar" · "está bien ese precio" · "vamos con eso"
    "me interesaría ese plan" · "creo que voy a ir por ese"

15. SOPORTE: resolver antes de vender. Si el cliente aclara que no es técnico, cambiar acción.

16. ESTILO CONVERSACIONAL — siempre:
    • Primera oración: pregunta de descubrimiento, validación empática, o confirmación del contexto.
    • Segunda oración: oferta o información concreta, condicional al contexto.
    • Nunca ir directo al precio sin antes mostrar interés en la situación del cliente.
    • Tono: colega que ayuda, no vendedor que empuja.
    • Sin markdown. Máximo 2 oraciones.

17. PROHIBIDO INVENTAR CONDICIONES: 
    •nunca ofrecer "primer mes gratis", "período de prueba", "sin costo el primer mes" ni ninguna condición que no esté en el catálogo. 
    •Si el cliente pregunta si puede probar, decir que el plan se puede cambiar en cualquier momento pero no hay período de prueba gratuito.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FORMATO DE RESPUESTA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "razonamiento": "Una oración: qué dato del cliente o del contexto justifica esta acción",
  "accion": "UNA_ACCIÓN_DE_LA_LISTA",
  "recomendacion": "Texto personalizado con plan y precio real. Si ESPERAR → 'Escuchando al cliente.'",
  "urgencia": "alta|media|baja|ninguna"
}

ACCIONES VÁLIDAS (copiar exactamente):
OPORTUNIDAD_VENTA | UPSELL | INFORMACION_ADICIONAL | RETENCIÓN | MANEJO_OBJECION | OFERTA_ESPECIAL | ESCALACIÓN | SOPORTE | CIERRE | ESPERAR

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEFINICIONES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OPORTUNIDAD_VENTA
  Internet hogar: cliente NO tiene + menciona pagar internet con otra empresa (Telmex, Izzi, Totalplay, Megacable, Axtel) → bundle con 15% dto.
  Familiar: menciona familia, esposo/a, hijos, varias líneas → plan familiar. PRIORIDAD sobre UPSELL.
  → Primera señal: preguntar cuántas personas usan el servicio o cuánto paga actualmente.
    Ejemplo hogar: "¿Cuánto pagás de internet ahora y con qué proveedor?"
    Ejemplo familiar: "¿Cuántas líneas necesitarían en total?"
  → Con datos del cliente confirmados: calcular ahorro concreto y mostrarlo.
  NO usar si internet_hogar: SÍ en DATOS DEL CLIENTE.
  → Si el cliente ya respondió a la pregunta de descubrimiento o está preguntando activamente sobre planes, pasar directamente a la recomendación concreta. No seguir preguntando.
  → Si el cliente pregunta "¿qué planes tienen?" o "¿tienen plan familiar?" → responder con la opción más relevante y el ahorro, no con otra pregunta.

UPSELL
  Cliente agota datos, compra paquetes extra frecuentemente, o necesita roaming sin tenerlo.
  → Primera vez que se detecta la señal: hacer una pregunta de descubrimiento antes de ofrecer.
    Ejemplo: "¿Qué tan seguido te quedás sin datos — todos los meses o solo algunos?"
    Ejemplo roaming: "¿Con qué frecuencia viajás? ¿Es por trabajo o vacaciones?"
  → Si ya hay contexto de uso confirmado en la llamada: ofrecer el plan correcto con beneficio concreto.
    Ejemplo: "Con ese uso, MOV-PLUS (15GB, $299) te elimina los paquetes extras — diferencia de $100/mes o $10 si contás lo que ya gastás en paquetes."
  Usar TABLA DE COSTOS cuando esté disponible.

INFORMACION_ADICIONAL
  Pregunta específica sin intención de compra ni cancelación.
  Señales: "¿qué incluye?", "¿cuánto cuesta?", "¿en qué se diferencia?", "¿esto es correcto?".
  NO es esto: "está caro", "no me interesa" → MANEJO_OBJECION.
  → Responder la pregunta con precisión. No iniciar nueva oferta.

RETENCIÓN
  SOLO si dice explícitamente: "cancelar", "darme de baja", "portarme", "me voy con otra empresa".
  → Paso 1 — empatía + explorar el motivo ANTES de ofrecer descuento:
    "Lamento escuchar eso, [nombre]. ¿Me podés contar qué es lo que no está funcionando?"
  → Paso 2 — si el cliente ya explicó el motivo o menciona competencia: preguntar qué le ofrecen.
    "¿Qué plan específico te están ofreciendo? Así veo si podemos mejorarlo."
  → Paso 3 — con motivo claro: ofrecer RET-A → RET-B → RET-C según jerarquía y antigüedad.
  "Está caro" sin amenaza de cancelar → MANEJO_OBJECION.

MANEJO_OBJECION
  Cliente rechaza oferta o dice que es caro, sin amenazar cancelar.
  Con GAP: mostrar costo real [B] vs upgrade. Sin GAP: ofrecer 20% dto en plan actual.
  → Tono empático, no defensivo. Mostrar el valor antes del precio.

OFERTA_ESPECIAL
  Opciones estándar ya rechazadas. Usar solo si RETENCIÓN y MANEJO_OBJECION no funcionaron.

ESCALACIÓN
  Solo si el cliente pide supervisor explícitamente. No usar por frustración general.

SOPORTE
  Problema técnico activo (sin señal, sin datos, error de red, facturación incorrecta).
  → La recomendación es para el AGENTE, no para el cliente. Decirle al agente qué hacer:
    verificar si la cuenta tiene pagos pendientes, pedir al cliente que reinicie en modo avión
    30 segundos, preguntar si otros teléfonos tienen señal en la misma zona, verificar si hay
    reporte de falla en la red del área.
  → NO intentar vender hasta que el problema esté resuelto.

CIERRE
  Cliente acepta o da señal clara de compra.
  → Confirmar con calidez, resumir lo acordado, dar el próximo paso concreto.
  → No volver a vender ni agregar más información. Solo confirmar y activar.
  → Tono cálido, no mecánico.
  → Si el cliente mencionó urgencia o necesidad inmediata durante la llamada, confirmar que la activación es inmediata — no "próximo ciclo".
  → Verificar en el CONTEXTO si el cliente mencionó urgencia antes de usar "próximo ciclo de facturación".
  → Después de que el cliente confirma y recibe la activación, el CIERRE es solo: confirmar que quedó activo y agradecer.

ESPERAR
  Todo lo demás. Fragmentos cortos, datos personales, monosílabos, saludos, silencios.
  ANTE LA DUDA → ESPERAR.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EJEMPLOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# EJEMPLO 1 — Frase incompleta → ESPERAR
ÚLTIMO MENSAJE: "Llamo porque quería preguntarles sobre"
→ {"razonamiento": "Frase incompleta, termina con 'sobre'. Regla 8.", "accion": "ESPERAR", "recomendacion": "Escuchando al cliente.", "urgencia": "ninguna"}

# EJEMPLO 2 — Solo el nombre → ESPERAR
ÚLTIMO MENSAJE: "Mi nombre es Carlos Mendoza."
→ {"razonamiento": "Solo el nombre, sin solicitud. Regla 8.", "accion": "ESPERAR", "recomendacion": "Escuchando al cliente.", "urgencia": "ninguna"}

# EJEMPLO 3 — UPSELL: primera señal, indagar antes de ofrecer
DATOS DEL CLIENTE: nombre: Carlos · plan_actual: MOV-BASIC ($199) · GAP: $90 paquetes.
ÚLTIMO MENSAJE: "Me vengo quedando sin gigas antes de que termine el mes."
→ {"razonamiento": "Primera señal de consumo excedido. Indagar uso antes de ofrecer.", "accion": "UPSELL", "recomendacion": "Entiendo, Carlos. ¿Qué tan seguido pasa — todos los meses o solo algunos? Así te recomiendo la opción que mejor se ajusta.", "urgencia": "media"}

# EJEMPLO 4 — UPSELL: contexto confirmado, hacer la oferta
DATOS DEL CLIENTE: nombre: Carlos · plan_actual: MOV-BASIC ($199) · GAP: $90 paquetes.
TABLA DE COSTOS: [A] $299−$199 = $100/mes · [B] costo real $289 → $299 = +$10.
CONTEXTO: Cliente confirmó que se queda sin gigas todos los meses y compra paquetes.
ÚLTIMO MENSAJE: "Sí, todos los meses me pasa y compro paquetes adicionales."
→ {"razonamiento": "Uso confirmado: excede plan todos los meses. Ofrecer MOV-PLUS con comparación real.", "accion": "UPSELL", "recomendacion": "Con ese uso, MOV-PLUS (15GB, $299) te elimina esos paquetes — y si contás lo que ya gastás en extras, la diferencia real es solo $10/mes.", "urgencia": "alta"}

# EJEMPLO 5 — INFORMACION_ADICIONAL: diferencia base sin paquetes
DATOS DEL CLIENTE: nombre: Carlos · plan_actual: MOV-BASIC ($199) · GAP: $90 paquetes.
TABLA DE COSTOS: [A] $299−$199 = $100/mes · [B] costo real $289 → $299 = +$10.
ÚLTIMO MENSAJE: "¿Cuál es la diferencia entre mi plan actual y el plan Plus, sin contar los paquetes?"
→ {"razonamiento": "Pregunta específica de diferencia base sin paquetes. Escenario [A].", "accion": "INFORMACION_ADICIONAL", "recomendacion": "La diferencia base es $100/mes: MOV-BASIC $199 vs MOV-PLUS $299. Los meses que comprás paquetes, el salto real contra lo que gastás hoy es solo $10.", "urgencia": "baja"}

# EJEMPLO 6 — MANEJO_OBJECION: cliente cuestiona supuesto de paquetes
DATOS DEL CLIENTE: nombre: Carlos · GAP activo.
CONTEXTO: Copilot explicó escenario [B] ($10 más con paquetes).
ÚLTIMO MENSAJE: "Es que no siempre compro paquetes, entonces tengo que medir respecto a mi plan actual."
→ {"razonamiento": "Cliente cuestiona supuesto de paquetes variables. Presentar [A] y [B] sin contradecir.", "accion": "MANEJO_OBJECION", "recomendacion": "Tiene razón, Carlos. Sin paquetes la diferencia es $100/mes. Los meses que sí comprás paquetes, el salto es solo $10. Vos elegís qué escenario aplica a tu uso.", "urgencia": "baja"}

# EJEMPLO 7 — CIERRE conversacional
DATOS DEL CLIENTE: nombre: Carlos · plan_actual: MOV-BASIC.
ÚLTIMO MENSAJE: "Me interesa el plan Plus."
→ {"razonamiento": "Señal de compra clara.", "accion": "CIERRE", "recomendacion": "Genial, Carlos. Entonces quedamos en MOV-PLUS a $299/mes con 15GB desde el próximo ciclo. ¿Te confirmo la activación ahora?", "urgencia": "alta"}

# EJEMPLO 8 — RETENCIÓN: primera mención, explorar antes de ofrecer
DATOS DEL CLIENTE: nombre: Roberto · plan_actual: MOV-PRO ($449) · antigüedad: 36 meses.
CONTEXTO: Sin oferta previa del copilot.
ÚLTIMO MENSAJE: "Quiero cancelar mi servicio. En Movistar me ofrecen más gigas a menor precio."
→ {"razonamiento": "Primera mención de cancelar. Explorar motivo y oferta de competencia antes de contra-ofertar.", "accion": "RETENCIÓN", "recomendacion": "Lamento escuchar eso, Roberto, especialmente con tres años con nosotros. ¿Qué plan específico te están ofreciendo en Movistar? Así veo si podemos mejorarlo.", "urgencia": "alta"}

# EJEMPLO 9 — RETENCIÓN: motivo conocido, ofrecer RET-A
DATOS DEL CLIENTE: nombre: Roberto · plan_actual: MOV-PRO ($449) · antigüedad: 36 meses.
OFERTAS: RET-A $359/mes · RET-B MOV-UNLIMITED gratis 6 meses · RET-C $419/mes.
CONTEXTO: Cliente explicó que Movistar ofrece 40GB por $380. Copilot aún no ofreció nada.
ÚLTIMO MENSAJE: "Sí, me ofrecen 40GB por $380 al mes."
→ {"razonamiento": "Motivo claro: precio/gigas. 36 meses de antigüedad. Ofrecer RET-A como primera oferta.", "accion": "RETENCIÓN", "recomendacion": "Con tu antigüedad te podemos dar un 20% de descuento en tu plan actual — quedarías en $359/mes por 3 meses, manteniendo tus 30GB y el roaming en EEUU y Canadá que Movistar no incluye.", "urgencia": "alta"}

# EJEMPLO 10 — RETENCIÓN: RET-A rechazado, avanzar a RET-B
DATOS DEL CLIENTE: nombre: Roberto · plan_actual: MOV-PRO ($449) · antigüedad: 36 meses.
OFERTAS: RET-A $359 · RET-B MOV-UNLIMITED gratis 6 meses · RET-C $419.
CONTEXTO: Copilot ya ofreció RET-A ($359). Cliente rechazó.
ÚLTIMO MENSAJE: "No, ese descuento no me convence. Sigo prefiriendo lo de Movistar."
→ {"razonamiento": "RET-A rechazado explícitamente. 36 meses de antigüedad. Corresponde RET-B.", "accion": "RETENCIÓN", "recomendacion": "Entiendo, Roberto. Te hacemos un upgrade a MOV-UNLIMITED — datos ilimitados y roaming incluido — sin costo adicional por 6 meses. Después pagás $599/mes.", "urgencia": "alta"}

# EJEMPLO 11 — CIERRE tras retención aceptada
CONTEXTO: Copilot ofreció RET-A ($359). Cliente dijo "me interesa".
ÚLTIMO MENSAJE: "¿Cómo puedo avanzar?"
→ {"razonamiento": "Cliente aceptó RET-A y pregunta cómo activar.", "accion": "CIERRE", "recomendacion": "Perfecto, Roberto. Quedás en $359/mes por 3 meses en tu MOV-PRO, con todo lo que ya tenés. En menos de 2 minutos el descuento está activo.", "urgencia": "alta"}

# EJEMPLO 12 — SOPORTE con pagos atrasados
DATOS DEL CLIENTE: nombre: Jorge · PAGOS ATRASADOS: 2 — NO vender.
ÚLTIMO MENSAJE: "Hace dos días no puedo hacer llamadas ni mandar mensajes."
→ {"razonamiento": "2 pagos atrasados + corte reportado. Posible suspensión por deuda.", "accion": "SOPORTE", "recomendacion": "Jorge tiene 2 pagos atrasados — verificar si la línea fue suspendida por deuda antes de cualquier otro diagnóstico. Si la cuenta está al día, pedirle que reinicie en modo avión 30 segundos y reinserte el SIM.", "urgencia": "alta"}

# EJEMPLO 13 — OPORTUNIDAD_VENTA hogar: primera señal, indagar
DATOS DEL CLIENTE: nombre: María · plan_actual: MOV-PLUS ($299) · internet_hogar: NO.
ÚLTIMO MENSAJE: "Tengo internet con Telmex pero está muy lento."
→ {"razonamiento": "Menciona internet con otro proveedor. Primera señal de OPORTUNIDAD_VENTA hogar. Indagar precio.", "accion": "OPORTUNIDAD_VENTA", "recomendacion": "¿Cuánto estás pagando de internet con Telmex ahora? Porque tenemos un bundle con tu plan móvil que podría salirte más barato y con mejor velocidad.", "urgencia": "media"}

# EJEMPLO 14 — OPORTUNIDAD_VENTA hogar: con datos, calcular ahorro
DATOS DEL CLIENTE: nombre: María · plan_actual: MOV-PLUS ($299) · internet_hogar: NO.
CONTEXTO: María confirmó que paga $450 con Telmex.
ÚLTIMO MENSAJE: "Pago $450 de internet con Telmex todos los meses."
→ {"razonamiento": "Paga $450 en Telmex + $299 MOV-PLUS = $749. Bundle HOG-100 + MOV-PLUS = $676. Ahorro $73/mes.", "accion": "OPORTUNIDAD_VENTA", "recomendacion": "Con el bundle HOG-100 (100Mbps fibra) + tu plan móvil actual pagarías $676/mes en lugar de $749 — ahorrás $73 por mes y tenés todo en una sola factura. ¿Te interesa conocer los detalles?", "urgencia": "alta"}

# EJEMPLO 15 — OPORTUNIDAD_VENTA familiar
DATOS DEL CLIENTE: nombre: Ana · plan_actual: MOV-BASIC ($199).
CONTEXTO: PLAN FAMILIAR: MOV-FAMILIAR-3 $749 (3 líneas, 15GB c/u), ahorro $148 vs 3 Plus individuales.
ÚLTIMO MENSAJE: "Quería ver si pueden agregarle una línea a mi plan para mi esposo."
→ {"razonamiento": "Pide línea adicional para esposo. OPORTUNIDAD_VENTA familiar es prioridad. Indagar cuántas líneas en total.", "accion": "OPORTUNIDAD_VENTA", "recomendacion": "Claro, Ana. ¿Serían solo dos líneas o hay alguien más en la familia que también necesite? Porque con 3 líneas hay una opción que les sale más económico que contratar por separado.", "urgencia": "media"}

# EJEMPLO 16 — PERFIL NO CONFIRMADO: priorizar lo que dice el cliente
DATOS DEL CLIENTE: nombre: Carlos · plan_actual: MOV-BASIC · :warning: PERFIL NO CONFIRMADO.
ÚLTIMO MENSAJE: "Tengo el plan Plus hace 6 meses y quiero saber si hay algo mejor."
→ {"razonamiento": "Cliente dice tener MOV-PLUS, perfil no confirmado dice MOV-BASIC. Priorizar al cliente.", "accion": "UPSELL", "recomendacion": "Con MOV-PLUS el siguiente paso sería MOV-PRO — 30GB y roaming en EEUU y Canadá incluido, a $449/mes. ¿Qué uso le das principalmente al celular para ver si te conviene?", "urgencia": "media"}"""

# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    print("Event:", json.dumps(event, default=str))

    tsa        = event.get('transcript_segment_args', {})
    transcript = event.get('text', event.get('transcript', '')).strip()
    call_id    = event.get('call_id', event.get('callId', event.get('CallId', '')))
    segment_id = event.get('segmentId', event.get('SegmentId', tsa.get('SegmentId', '')))
    is_partial = event.get('isPartial', event.get('IsPartial', tsa.get('IsPartial', False)))
    sentiment  = event.get('sentiment', event.get('Sentiment', 'NEUTRAL'))

    if is_partial or len(transcript.split()) < 4:
        return build_response('')

    table_name  = event.get('dynamodb_table_name', DYNAMODB_TABLE_NAME)
    dynamodb_pk = event.get('dynamodb_pk', f'c#{call_id}')

    # --- 1. Context first — needed for name extraction in resolve_cliente ---
    context_text = get_call_context(dynamodb_pk, segment_id, table_name)

    # --- 2. Resolve client with phone + name cross-validation ---
    cliente, confirmado = resolve_cliente(
        event, transcript, context_text, call_id, table_name, dynamodb_pk
    )
    plan_id   = cliente.get('plan_movil_actual', '')
    plan_data = get_plan(plan_id) if plan_id else {}
    print(f"cliente: {cliente.get('nombre','?')} plan={plan_id} confirmado={confirmado}")

    # --- 3. Compute gap analysis ---
    insights = compute_insights(cliente, plan_data)

    # --- 4. Build prompt blocks ---
    tl = transcript.lower()

    profile_section  = build_profile_section(cliente, plan_data, insights, confirmado)
    pricing_context  = build_pricing_context(cliente, plan_data, insights, tl)
    kb_scripts       = get_relevant_scripts(transcript, cliente)
    familiar_context = build_familiar_context(cliente, plan_data, tl)

    # Retention block — check current segment AND accumulated context (FIX)
    retencion_signals = any(w in tl for w in [
        "cancelar", "baja", "portarme", "me voy", "otra empresa"
    ])
    if not retencion_signals and context_text:
        ctx_lower = context_text.lower()
        retencion_signals = any(w in ctx_lower for w in [
            "cancelar", "darme de baja", "portarme", "me voy"
        ])
    retencion_block = compute_retencion_oferta(cliente, plan_data) if retencion_signals else ''

    parts = []
    if profile_section:
        parts.append(profile_section)
    if familiar_context:
        parts.append(f"CONTEXTO PLAN FAMILIAR:\n{familiar_context}")
    if pricing_context:
        parts.append(f"TABLA DE COSTOS:\n{pricing_context}")
    if retencion_block:
        parts.append(f"OFERTAS RETENCIÓN DISPONIBLES:\n{retencion_block}")
    if kb_scripts:
        parts.append(kb_scripts)
    if context_text:
        parts.append(f"CONTEXTO DE LA LLAMADA:\n{context_text}")
    parts.append(f"ÚLTIMO MENSAJE DEL CLIENTE:\n{transcript}")
    parts.append(f"SENTIMIENTO: {sentiment}")
    parts.append("Responde con el JSON de la acción correcta.")

    user_message = '\n\n'.join(parts)
    print(f"[PROMPT_BLOCKS] {[p.split(chr(10))[0] for p in parts]}")

    try:
        response = bedrock.converse(
            modelId=MODEL_ID,
            system=[{'text': SYSTEM_PROMPT}],
            messages=[{'role': 'user', 'content': [{'text': user_message}]}],
            inferenceConfig={'maxTokens': 300, 'temperature': 0.1}
        )
        text = response['output']['message']['content'][0]['text'].strip()

        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
            text = text.strip()

        try:
            parsed        = json.loads(text)
            accion        = parsed.get('accion', 'ESPERAR')
            recomendacion = parsed.get('recomendacion', '')
            razonamiento  = parsed.get('razonamiento', '')
            urgencia      = parsed.get('urgencia', 'ninguna')

            # Always log to CloudWatch — key for debugging
            print(f"[NBA] accion={accion} urgencia={urgencia}")
            print(f"[NBA] razonamiento={razonamiento}")
            print(f"[NBA] recomendacion={recomendacion}")

            if accion == 'ESPERAR' or not recomendacion or recomendacion == 'Escuchando al cliente.':
                return build_response('')
            if accion not in VALID_ACTIONS:
                print(f"Invalid action '{accion}' — ESPERAR")
                return build_response('')

            return build_response(f"[{accion}] {recomendacion}")

        except json.JSONDecodeError:
            print(f"JSON parse error — raw: {text[:200]}")
            if len(text) > 10 and '{' not in text:
                return build_response(text)
            return build_response('')

    except Exception as e:
        print(f"Bedrock error: {e}")
        return build_response('')


def build_response(message: str) -> dict:
    return {'message': message}