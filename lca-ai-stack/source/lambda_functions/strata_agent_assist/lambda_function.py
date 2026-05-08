import boto3
import json
import os
import re
from decimal import Decimal
from boto3.dynamodb.conditions import Key

bedrock        = boto3.client('bedrock-runtime',       region_name='us-east-1')
bedrock_agent  = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
dynamodb       = boto3.resource('dynamodb',            region_name='us-east-1')

# LCA call-transcript table (existing)
DYNAMODB_TABLE_NAME  = os.environ.get('DYNAMODB_TABLE_NAME', '')
# New product/client tables
TABLA_PLANES    = os.environ.get('TABLA_PLANES',   'lca-poc-copilot-telco-planes')
TABLA_CLIENTES  = os.environ.get('TABLA_CLIENTES', 'lca-poc-copilot-telco-clientes')
TABLA_OFERTAS   = os.environ.get('TABLA_OFERTAS',  'lca-poc-copilot-telco-ofertas')

KNOWLEDGE_BASE_ID    = os.environ.get('KNOWLEDGE_BASE_ID', '')
MODEL_ID             = os.environ.get('MODEL_ID', 'us.anthropic.claude-haiku-4-5-20251001-v1:0')
MAX_CONTEXT_SEGMENTS = 10

VALID_ACTIONS = {
    'CROSS_SELL', 'UPSELL', 'RETENCIÓN', 'MANEJO_OBJECION',
    'OFERTA_ESPECIAL', 'ESCALACIÓN', 'SOPORTE', 'CIERRE', 'ESPERAR'
}

# Module-level caches — reused across warm Lambda invocations
_cliente_cache: dict = {}   # telefono  → item dict
_plan_cache:    dict = {}   # plan_id   → item dict
_oferta_cache:  dict = {}   # oferta_id → item dict


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _ddb_to_native(obj):
    """Recursively convert DynamoDB Decimal to int/float so arithmetic works."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _ddb_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ddb_to_native(i) for i in obj]
    return obj


def _normalize_phone(phone: str) -> str:
    """Strip +, spaces, dashes → '525512345678'."""
    return re.sub(r'[\s\+\-\(\)]', '', phone)


def get_cliente(telefono: str) -> dict:
    key = _normalize_phone(telefono)
    if key in _cliente_cache:
        return _cliente_cache[key]
    try:
        table = dynamodb.Table(TABLA_CLIENTES)
        resp  = table.get_item(Key={'telefono': key})
        item  = _ddb_to_native(resp.get('Item', {}))
        _cliente_cache[key] = item
        return item
    except Exception as e:
        print(f"DDB get_cliente error: {e}")
        return {}


def get_plan(plan_id: str) -> dict:
    if plan_id in _plan_cache:
        return _plan_cache[plan_id]
    try:
        table = dynamodb.Table(TABLA_PLANES)
        resp  = table.get_item(Key={'plan_id': plan_id})
        item  = _ddb_to_native(resp.get('Item', {}))
        _plan_cache[plan_id] = item
        return item
    except Exception as e:
        print(f"DDB get_plan error: {e}")
        return {}


def get_oferta(oferta_id: str) -> dict:
    if oferta_id in _oferta_cache:
        return _oferta_cache[oferta_id]
    try:
        table = dynamodb.Table(TABLA_OFERTAS)
        resp  = table.get_item(Key={'oferta_id': oferta_id})
        item  = _ddb_to_native(resp.get('Item', {}))
        _oferta_cache[oferta_id] = item
        return item
    except Exception as e:
        print(f"DDB get_oferta error: {e}")
        return {}


def get_bundle_config() -> dict:
    return get_plan('CONFIG#BUNDLE')


def build_familiar_context(cliente: dict, plan_data: dict, tl: str) -> str:
    """
    Explicit familiar plan options with real DynamoDB prices.
    Prevents hallucinations about 'datos ilimitados', wrong savings, or non-existent plans.
    """
    familiar_signals = any(w in tl for w in [
        "familiar", "familia", "esposo", "esposa", "hijo", "hija",
        "líneas", "lineas", "dos líneas", "varias líneas", "agregar línea"
    ])
    if not familiar_signals:
        return ''

    fam3 = get_plan('MOV-FAMILIAR-3')
    fam5 = get_plan('MOV-FAMILIAR-5')
    plan_id     = cliente.get('plan_movil_actual', 'MOV-BASIC')
    plan_precio = plan_data.get('precio', 199)

    lines = ["OPCIONES PLAN FAMILIAR (usar EXACTAMENTE estos datos, sin inventar):"]
    lines.append(f"• 2 planes individuales {plan_id}: 2×${plan_precio} = ${2*plan_precio}/mes")

    basic = get_plan('MOV-BASIC')
    plus  = get_plan('MOV-PLUS')
    if basic and plus:
        lines.append(f"• 2 planes MOV-BASIC: ${2*basic.get('precio',199)}/mes | 2 planes MOV-PLUS: ${2*plus.get('precio',299)}/mes")

    if fam3:
        p3  = fam3.get('precio', 749)
        gb3 = fam3.get('datos_gb_por_linea', 15)
        ah3 = fam3.get('ahorro_vs_individual_mxn', 148)
        lines.append(f"• MOV-FAMILIAR-3: ${p3}/mes — 3 líneas, {gb3}GB POR LÍNEA (no son ilimitados ni compartidos). Ahorro real: ${ah3}/mes vs 3 planes MOV-PLUS individuales.")

    if fam5:
        p5  = fam5.get('precio', 1099)
        gb5 = fam5.get('datos_gb_por_linea', 15)
        ah5 = fam5.get('ahorro_vs_individual_mxn', 396)
        lines.append(f"• MOV-FAMILIAR-5: ${p5}/mes — 5 líneas, {gb5}GB POR LÍNEA. Ahorro real: ${ah5}/mes vs 5 planes MOV-PLUS individuales.")

    lines.append("REGLA: No existe plan de 2 líneas. Si el cliente quiere exactamente 2 líneas → ofrecer 2 planes individuales O el familiar de 3 líneas explicando que tiene 1 línea extra disponible.")
    lines.append("PROHIBIDO: No inventar descuentos, no usar precios de retención en este contexto.")

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Phone extraction from Lambda event
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
    """Fallback: read CustomerPhoneNumber from the LCA call record."""
    name = table_name or DYNAMODB_TABLE_NAME
    if not name or not call_id:
        return ''
    pk = pk_override or f'c#{call_id}'
    try:
        table = dynamodb.Table(name)
        resp  = table.query(KeyConditionExpression=Key('PK').eq(pk), Limit=10)
        items = resp.get('Items', [])
        print(f"phone lookup: PK={pk}, items_found={len(items)}")
        for item in items:
            raw = (item.get('CustomerPhoneNumber') or
                   item.get('callerPhoneNumber')   or
                   item.get('CallerPhoneNumber')   or '')
            if raw:
                return _normalize_phone(raw)
        print(f"phone lookup: no phone field found in {len(items)} items")
    except Exception as e:
        print(f"LCA phone lookup error: {e}")
    return ''


# ---------------------------------------------------------------------------
# Insights: compute gap analysis from client + plan data
# ---------------------------------------------------------------------------

def compute_insights(cliente: dict, plan_data: dict) -> dict:
    """
    Pre-calculate data-gap and upsell economics so the LLM gets explicit numbers
    rather than having to infer them from raw text.
    """
    insights = {}

    consumo = cliente.get('consumo_promedio_gb')
    limite  = cliente.get('limite_plan_gb')

    if limite is None and plan_data:
        gb = plan_data.get('datos_gb')
        limite = gb if isinstance(gb, (int, float)) else None

    if not (consumo and limite and consumo > limite):
        return insights

    gap_gb = consumo - limite

    # Use recorded spend if available; otherwise estimate from config
    gasto_paquetes = cliente.get('gasto_paquetes_mensual')
    if gasto_paquetes is None:
        pkg_cfg        = get_plan('CONFIG#PAQUETES')
        precio_gb      = pkg_cfg.get('precio_paquete_gb', 30) if pkg_cfg else 30
        gasto_paquetes = gap_gb * precio_gb

    upgrade_id    = plan_data.get('upgrade')
    upgrade_data  = get_plan(upgrade_id) if upgrade_id else {}
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
            'upgrade_delta':  delta,
            'net_saving':     gasto_paquetes - delta,
        }

    return insights


def compute_retencion_oferta(cliente: dict, plan_data: dict) -> str:
    """Return retention offers ordered RET-A → RET-B → RET-C so the LLM offers them in sequence."""
    antiguedad     = cliente.get('antiguedad_meses', 0)
    plan_id        = plan_data.get('plan_id', '')
    plan_precio    = plan_data.get('precio', 0)
    upgrade_id     = plan_data.get('upgrade')
    upgrade_data   = get_plan(upgrade_id) if upgrade_id else {}
    upgrade_precio = upgrade_data.get('precio', 0)

    lines = []

    # RET-A — always offer first
    ret = get_oferta('RET-A')
    if ret:
        desc = ret.get('descuento_pct', 20)
        dur  = ret.get('duracion_meses', 3)
        lines.append(
            f"RET-A (ofrecer primero): {desc}% dto en plan actual "
            f"({plan_id} ${plan_precio}) → ${round(plan_precio * (1 - desc/100))}/mes por {dur} meses"
        )

    # RET-B — if client rejects RET-A and has 12+ months
    if upgrade_id and upgrade_precio and antiguedad >= 12:
        ret = get_oferta('RET-B')
        if ret:
            dur = ret.get('duracion_meses', 6)
            lines.append(
                f"RET-B (si rechaza RET-A): upgrade gratuito a {upgrade_id} "
                f"(${upgrade_precio}) por {dur} meses"
            )

    # RET-C — last resort, high-value clients only
    if upgrade_id and upgrade_precio and (antiguedad >= 24 or plan_precio >= 500):
        ret = get_oferta('RET-C')
        if ret:
            desc = ret.get('descuento_pct', 30)
            dur  = ret.get('duracion_meses', 3)
            lines.append(
                f"RET-C (último recurso, NO ofrecer directo): {upgrade_id} "
                f"(${upgrade_precio}) con {desc}% dto → "
                f"${round(upgrade_precio * (1 - desc/100))}/mes por {dur} meses"
            )

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Profile section builder
# ---------------------------------------------------------------------------

def build_profile_section(cliente: dict, plan_data: dict, insights: dict) -> str:
    if not cliente:
        return ''

    lines = []
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

    return "DATOS DEL CLIENTE:\n" + '\n'.join(f"• {l}" for l in lines)


# ---------------------------------------------------------------------------
# Call context from LCA DynamoDB
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
                ch   = item['Channel']
                role = 'Cliente' if ch == 'CALLER' else ('Agente' if ch == 'AGENT' else 'Copilot')
                sentiment = item.get('Sentiment', '')
                s         = f" [{sentiment}]" if sentiment and sentiment not in ('NEUTRAL', '') else ''
                segments.append(f"{role}{s}: {item['Transcript']}")
        segments.reverse()
        caller_count, filtered = 0, []
        for seg in segments:
            filtered.append(seg)
            if seg.startswith('Cliente'):  # only caller segments count toward the limit
                caller_count += 1
            if caller_count >= MAX_CONTEXT_SEGMENTS:
                break
        return '\n'.join(filtered)
    except Exception as e:
        print(f"DynamoDB context error: {e}")
        return ''


# ---------------------------------------------------------------------------
# Knowledge Base — semantic retrieval only
# ---------------------------------------------------------------------------

def query_kb(query: str, n: int = 3) -> str:
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
    """
    Fetch only descriptive/semantic content from KB.
    Exact pricing and rules come from DynamoDB — no need to search KB for those.
    """
    results = []
    tl = transcript.lower()

    plan_id      = cliente.get('plan_movil_actual', '')
    internet_hogar = cliente.get('internet_hogar', False)

    # Retención / cancelación
    if any(w in tl for w in ["cancelar", "baja", "portarme", "otra empresa",
                              "movistar", "at&t", "telcel", "competencia", "me voy"]):
        kb = query_kb("script retención cancelar qué decirle al cliente que quiere cancelar")
        if kb:
            results.append(f"SCRIPTS RETENCIÓN:\n{kb}")

    # Upsell por datos / roaming
    if any(w in tl for w in ["gigas", "datos", "paquetes", "me quedé", "no alcanza",
                              "roaming", "viaj", "estados unidos", "eeuu"]):
        kb = query_kb(f"argumentos upsell más datos plan superior {plan_id}")
        if kb:
            results.append(f"ARGUMENTOS UPSELL:\n{kb}")

    # Precio / objeción
    if any(w in tl for w in ["caro", "costoso", "muy caro", "no me alcanza", "más barato",
                              "descuento", "precio", "cuánto sería", "sale muy"]):
        kb = query_kb("manejo objeción precio caro descuento argumentos valor")
        if kb:
            results.append(f"MANEJO OBJECIÓN PRECIO:\n{kb}")

    # Cross-sell hogar / bundle
    if not internet_hogar:
        if any(w in tl for w in ["internet", "hogar", "casa", "telmex", "izzi",
                                  "totalplay", "megacable", "fibra", "wifi"]):
            kb = query_kb("bundle internet hogar móvil ahorro argumento cross-sell")
            if kb:
                results.append(f"ARGUMENTO BUNDLE:\n{kb}")

    # Plan familiar
    if any(w in tl for w in ["familiar", "familia", "esposo", "esposa", "hijo",
                              "líneas", "lineas", "varias líneas"]):
        kb = query_kb("plan familiar múltiples líneas argumento cross-sell familia")
        if kb:
            results.append(f"ARGUMENTO PLAN FAMILIAR:\n{kb}")

    # Soporte
    if any(w in tl for w in ["no funciona", "falla", "cobertura", "señal",
                              "lento", "problema", "no conecta"]):
        results.append("SOPORTE ACTIVO: Resolver el problema técnico antes de cualquier oferta comercial.")

    # Cierre
    if any(w in tl for w in ["lo quiero", "me interesa", "cómo lo activo",
                              "me quedo", "suena bien", "cuándo entra"]):
        kb = query_kb("frase cierre activar plan confirmar cliente acepta")
        if kb:
            results.append(f"CIERRE:\n{kb}")

    return '\n\n'.join(results)


# ---------------------------------------------------------------------------
# Precio calculado para contexto del LLM
# ---------------------------------------------------------------------------

def build_pricing_context(cliente: dict, plan_data: dict, insights: dict, tl: str) -> str:
    """
    Build explicit pricing options for the LLM.
    When a data-gap exists, shows a complete comparison table so the model
    never mixes the 'net $X more' framing with discounted prices.
    """
    lines = []
    plan_id     = cliente.get('plan_movil_actual', '')
    plan_precio = plan_data.get('precio', 0)
    upgrade_id  = plan_data.get('upgrade')
    gap         = insights.get('data_gap')

    price_signals = any(w in tl for w in ["caro", "costoso", "descuento",
                                           "más barato", "cuánto", "precio"])

    if price_signals and plan_precio:
        upgrade_data   = get_plan(upgrade_id) if upgrade_id else {}
        up_precio      = upgrade_data.get('precio', 0)

        if gap and up_precio:
            # Full comparison table — avoids mixing framings when discounts are involved
            costo_real = plan_precio + gap['extra_cost_est']
            lines.append("TABLA DE COSTOS (usar EXACTAMENTE estos números, no mezclar escenarios):")
            lines.append(f"  Costo real actual: ${plan_precio} (plan) + ${gap['extra_cost_est']} (paquetes extra) = ${costo_real}/mes")
            lines.append(f"  {upgrade_id} precio regular (${up_precio}):         ${up_precio - costo_real:+}/mes vs costo real actual")
            lines.append(f"  {upgrade_id} con 20% dto (${round(up_precio*0.80)}, 3 meses): ${round(up_precio*0.80) - costo_real:+}/mes vs costo real actual")
            lines.append(f"  {upgrade_id} con 30% dto (${round(up_precio*0.70)}, 3 meses): ${round(up_precio*0.70) - costo_real:+}/mes vs costo real actual")
            lines.append(f"  REGLA: El '+{up_precio - costo_real}' aplica SOLO al precio regular. Con descuento el cliente AHORRA vs su gasto actual.")
        else:
            # No gap — simple discount options
            lines.append(f"{plan_id} con 20% dto: ${round(plan_precio * 0.80)}/mes por 3 meses")
            if upgrade_id and up_precio:
                lines.append(f"Upgrade a {upgrade_id} (${up_precio}) gratis 6 meses (RET-B)")
                lines.append(f"{upgrade_id} con 30% dto: ${round(up_precio * 0.70)}/mes por 3 meses")

    # Bundle hogar (si no tiene y menciona internet)
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
                competitor_str = f" (actualmente paga ${precio_ih}/mes con {proveedor})" if precio_ih and proveedor else ''
                lines.append(
                    f"Bundle {plan_id} + HOG-100{competitor_str}: "
                    f"${total_con}/mes en lugar de ${total_sin} — ahorro ${ahorro}/mes"
                )

    return '\n'.join(lines) if lines else ''


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres el copilot inteligente de un agente de contact center de telecomunicaciones de TelcoStrata.
Tu objetivo es analizar la transcripción en tiempo real y sugerir la siguiente mejor acción (Next Best Action).

REGLAS ESTRICTAS:
1. Responde ÚNICAMENTE con un JSON válido. Sin markdown, sin texto adicional fuera del JSON.
2. CATÁLOGO CERRADO — IDs y precios exactos, sin excepción:
   MOV-BASIC $199 | MOV-PLUS $299 | MOV-PRO $449 | MOV-UNLIMITED $599
   MOV-FAMILIAR-3 $749 (3 líneas) | MOV-FAMILIAR-5 $1099 (5 líneas)
   HOG-50 $349 | HOG-100 $499 | HOG-300 $699 | HOG-GIGA $999
   "MOV-FAMILIA", "MOV-PRO-PLUS", "Plan Familiar Plus" NO EXISTEN. Si no está en esta lista, no lo menciones.
3. PRECIOS: usa solo los de DATOS DEL CLIENTE, PRECIOS CALCULADOS o el catálogo de arriba. Nunca calcules ni inventes precios.
4. NO OFRECER LO QUE YA TIENE: Si plan_actual está en DATOS DEL CLIENTE, NUNCA recomiendes ese mismo plan.
5. NO CROSS-SELL HOGAR si internet_hogar: SÍ está en DATOS DEL CLIENTE.
6. SEGMENTOS CORTOS (CRÍTICO): Menos de 4 palabras → ESPERAR. Ej: "sí", "no", "ok", "ajá", "um", ".".
7. SALUDOS → ESPERAR. NOMBRES → ESPERAR. Frase incompleta → ESPERAR.
8. PAGOS ATRASADOS: resolver primero, no vender.
9. SOPORTE: si el cliente ACLARA que no es problema técnico, cambiar de acción inmediatamente.
10. LONGITUD: Máximo 2 oraciones. Español latinoamericano neutro.
11. SOLICITUD EXPLÍCITA (CRÍTICO): Si el cliente dijo claramente lo que quiere ("plan familiar", "internet hogar", "roaming", "cancelar"), responder ÚNICAMENTE a eso. El GAP DE CONSUMO y otras oportunidades del perfil quedan IGNORADAS hasta resolver la solicitud del cliente. Revisar el CONTEXTO DE LA LLAMADA completo antes de decidir la acción.
12. PRODUCTOS INEXISTENTES: Si el cliente pide algo que no existe (ej. "plan de 2 líneas"), decirlo honestamente y ofrecer la alternativa más cercana. NUNCA inventar un producto ni un precio.
13. DESCUENTOS DE RETENCIÓN: Los descuentos RET-A/B/C son EXCLUSIVOS cuando el cliente amenaza cancelar. PROHIBIDO aplicarlos en UPSELL o CROSS_SELL. No inventar "descuento por antigüedad" fuera del contexto de retención.
14. DATOS DE PLANES: Usar ÚNICAMENTE los datos del CONTEXTO PLAN FAMILIAR o el catálogo. Los planes familiares tienen GB POR LÍNEA (no son "datos ilimitados" ni "datos compartidos"). No inventar beneficios.

ACCIONES VÁLIDAS (copiar exactamente):
CROSS_SELL | UPSELL | RETENCIÓN | MANEJO_OBJECION | OFERTA_ESPECIAL | ESCALACIÓN | SOPORTE | CIERRE | ESPERAR

FORMATO:
{
  "razonamiento": "Por qué esta acción, qué dato del cliente lo justifica",
  "accion": "UNA_ACCIÓN_DE_LA_LISTA",
  "recomendacion": "Texto personalizado con nombres de planes y precios reales. Si ESPERAR → 'Escuchando al cliente.'",
  "urgencia": "alta|media|baja|ninguna"
}

DEFINICIONES:

CROSS_SELL: Cliente NO tiene internet hogar + menciona pagar internet con otra empresa, o quiere agregar líneas.
  → Bundle: usar precios de PRECIOS CALCULADOS para mostrar ahorro exacto.
  → Familiar: si el cliente menciona "familiar", "familia", "esposo", "esposa", "hijo", "varias líneas" → CROSS_SELL plan familiar INMEDIATO. PRIORIDAD ABSOLUTA sobre cualquier UPSELL o GAP DE CONSUMO.
  → Opciones familiares: MOV-FAMILIAR-3 $749/mes (3 líneas) o MOV-FAMILIAR-5 $1099/mes (5 líneas).

UPSELL: Cliente agota datos, compra paquetes, necesita roaming sin tenerlo.
  → Si hay GAP DE CONSUMO y TABLA DE COSTOS disponible: usar los números exactos de la tabla.
  → El framing "solo $X más" aplica ÚNICAMENTE al precio regular del upgrade vs costo real actual.
  → Si hay descuento activo: comparar el precio con descuento vs costo real actual — puede resultar en AHORRO, no en costo mayor.
  → NUNCA combinar el framing "solo $X más" con un precio que ya tiene descuento aplicado.

RETENCIÓN: SOLO si dice explícitamente "cancelar", "darme de baja", "portarme", "me voy con otra empresa".
  → Usar jerarquía de PRECIOS CALCULADOS: RET-A → RET-B → RET-C según antigüedad.
  → "Está caro" sin amenaza de cancelar → MANEJO_OBJECION, no RETENCIÓN.

MANEJO_OBJECION: Cliente duda, dice que es caro, rechaza oferta, sin amenazar con cancelar.
  → Si tiene GAP DE CONSUMO: mostrar costo real actual (plan + paquetes) vs plan superior.
  → Si no hay gap: descuento 20% en plan actual o plan inferior si los datos le alcanzan.
  → Usar precios de PRECIOS CALCULADOS.

OFERTA_ESPECIAL: Cuando opciones estándar fueron rechazadas.

ESCALACIÓN: Solo si pide explícitamente hablar con supervisor.

SOPORTE: Problema técnico activo. Resolver antes de vender.

CIERRE: Cliente acepta o muestra intención clara de compra. Señales:
  "lo quiero", "me quedo con ese", "suena bien", "cómo lo activo", "cuándo entra en vigor",
  "me interesaría ese plan", "quiero ese plan con ese descuento", "me lo das con ese descuento",
  "está bien ese precio", "lo tomamos", "me convence".
  → Confirmar plan, precio final y próximos pasos. No volver a vender.

ESPERAR: Todo lo demás. ANTE LA DUDA → ESPERAR."""


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    print("Event:", json.dumps(event, default=str))

    tsa         = event.get('transcript_segment_args', {})
    transcript  = event.get('text', event.get('transcript', '')).strip()
    call_id     = event.get('call_id', event.get('callId', event.get('CallId', '')))
    segment_id  = event.get('segmentId', event.get('SegmentId', tsa.get('SegmentId', '')))
    is_partial  = event.get('isPartial', event.get('IsPartial', tsa.get('IsPartial', False)))
    sentiment   = event.get('sentiment', event.get('Sentiment', 'NEUTRAL'))

    if is_partial or len(transcript.split()) < 4:
        return build_response('')

    table_name   = event.get('dynamodb_table_name', DYNAMODB_TABLE_NAME)
    dynamodb_pk  = event.get('dynamodb_pk', f'c#{call_id}')

    # --- 1. Identify client via phone ---
    phone = get_customer_phone_from_event(event)
    if not phone:
        phone = get_phone_from_lca_dynamodb(call_id, table_name, dynamodb_pk)
    print(f"phone resolved: '{phone}'")

    cliente   = get_cliente(phone) if phone else {}
    plan_id   = cliente.get('plan_movil_actual', '')
    plan_data = get_plan(plan_id) if plan_id else {}
    print(f"cliente: {cliente.get('nombre','?')} plan={plan_id}")

    # --- 2. Compute gap analysis ---
    insights = compute_insights(cliente, plan_data)

    # --- 3. Fetch call transcript context ---
    context_text = get_call_context(dynamodb_pk, segment_id, table_name)

    # --- 4. Build prompt blocks ---
    tl = transcript.lower()

    profile_section  = build_profile_section(cliente, plan_data, insights)
    pricing_context  = build_pricing_context(cliente, plan_data, insights, tl)
    kb_scripts       = get_relevant_scripts(transcript, cliente)

    # Retention options (only when retention signals detected)
    retencion_block = ''
    if any(w in tl for w in ["cancelar", "baja", "portarme",
                              "me voy", "otra empresa"]):
        retencion_block = compute_retencion_oferta(cliente, plan_data)

    familiar_context = build_familiar_context(cliente, plan_data, tl)

    parts = []
    if profile_section:
        parts.append(profile_section)
    if familiar_context:
        parts.append(f"CONTEXTO PLAN FAMILIAR:\n{familiar_context}")
    if pricing_context:
        parts.append(f"PRECIOS CALCULADOS:\n{pricing_context}")
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
            parsed       = json.loads(text)
            accion       = parsed.get('accion', 'ESPERAR')
            recomendacion = parsed.get('recomendacion', '')

            if accion == 'ESPERAR' or not recomendacion or recomendacion == 'Escuchando al cliente.':
                return build_response('')
            if accion not in VALID_ACTIONS:
                print(f"Invalid action '{accion}' — ESPERAR")
                return build_response('')

            return build_response(f"[{accion}] {recomendacion}")

        except json.JSONDecodeError:
            if len(text) > 10 and '{' not in text:
                return build_response(text)
            return build_response('')

    except Exception as e:
        print(f"Bedrock error: {e}")
        return build_response('')


def build_response(message: str) -> dict:
    return {'message': message}
