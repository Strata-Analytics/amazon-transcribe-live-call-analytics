import boto3
import json
import os
from boto3.dynamodb.conditions import Key

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
bedrock_agent = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', '')
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID', '')
MAX_CONTEXT_SEGMENTS = 10

PLAN_PRICES = {
    "MOV-BASIC": 199, "MOV-PLUS": 299, "MOV-PRO": 449, "MOV-UNLIMITED": 599,
    "HOG-50": 349, "HOG-100": 499, "HOG-300": 699, "HOG-GIGA": 999,
}
PLAN_UPGRADES = {
    "MOV-BASIC": "MOV-PLUS", "MOV-PLUS": "MOV-PRO", "MOV-PRO": "MOV-UNLIMITED",
    "HOG-50": "HOG-100", "HOG-100": "HOG-300", "HOG-300": "HOG-GIGA",
}
DEMO_NAMES = [
    "Carlos", "Mendoza", "María", "González", "Roberto", "Hernández",
    "Ana", "Martínez", "Jorge", "Ramírez", "Lucía", "Torres",
]
VALID_ACTIONS = {
    'CROSS_SELL', 'UPSELL', 'RETENCIÓN', 'MANEJO_OBJECION',
    'OFERTA_ESPECIAL', 'ESCALACIÓN', 'SOPORTE', 'CIERRE', 'ESPERAR'
}

SYSTEM_PROMPT = """Eres el copilot inteligente de un agente de contact center de telecomunicaciones de TelcoStrata.
Tu objetivo es analizar la transcripción en tiempo real y sugerir la siguiente mejor acción (Next Best Action) basándote en el contexto real de la conversación y los catálogos de productos.

REGLAS ESTRICTAS:
1. Responde ÚNICAMENTE con un JSON válido. Sin markdown, sin texto adicional fuera del JSON.
2. CATÁLOGO REAL: Usa exclusivamente IDs y precios reales: MOV-BASIC $199, MOV-PLUS $299, MOV-PRO $449, MOV-UNLIMITED $599, HOG-50 $349, HOG-100 $499, HOG-300 $699, HOG-GIGA $999.
3. ANTI-PLACEHOLDER: NUNCA uses variables entre corchetes. MAL: "[PLAN_SUPERIOR]". BIEN: "MOV-PRO ($449)".
4. PERFIL DEL CLIENTE: Si hay perfil disponible, úsalo SOLO para conocer datos objetivos (plan actual, precio, antigüedad, consumo). NO decidas la recomendación basándote en campos predefinidos del perfil — decidila según la conversación real.
5. NO OFRECER LO QUE YA TIENE: Si el perfil indica internet_hogar: true, NO ofrecer bundle de hogar ni plan HOG.
6. SEGMENTOS CORTOS (CRÍTICO): Menos de 4 palabras, fragmento sin sentido, letra suelta, monosílabo → ESPERAR sin excepción. Ejemplos que son ESPERAR: "vale", "ehm", "m.", "sí", "no", "ok", "estado", "claro", "ajá".
7. SALUDOS → ESPERAR siempre: "Hola", "Buenos días", "Buenas tardes", "Buenas noches".
8. NOMBRES → ESPERAR: Cuando el cliente dice su nombre, esperar sin actuar.
9. NO ANTICIPAR: Si el cliente sigue hablando (frase incompleta), esperar a que termine.
10. LONGITUD: Máximo 2 oraciones. Español latinoamericano neutro.

LISTA EXACTA DE ACCIONES VÁLIDAS — COPIAR EXACTAMENTE, SIN VARIANTES:
CROSS_SELL | UPSELL | RETENCIÓN | MANEJO_OBJECION | OFERTA_ESPECIAL | ESCALACIÓN | SOPORTE | CIERRE | ESPERAR

FORMATO DE RESPUESTA:
{
  "razonamiento": "Una oración explicando por qué elegiste esta acción basándote en el mensaje actual",
  "accion": "UNA_ACCIÓN_DE_LA_LISTA",
  "recomendacion": "Texto con planes y precios reales. Si ESPERAR → 'Escuchando al cliente.'",
  "urgencia": "alta|media|baja|ninguna"
}

DEFINICIONES:

CROSS_SELL: Cliente NO tiene internet hogar y menciona pagar internet con otra empresa, o quiere agregar líneas familiares.
  → Calcular ahorro del bundle. Ejemplo: "Con MOV-PLUS + HOG-100 pagarías $676 en lugar de $749, ahorrando $73/mes."
  → NO usar si internet_hogar: true en el perfil.

UPSELL: Cliente agota sus datos, compra paquetes adicionales, o necesita roaming y su plan no lo incluye.
  → Ofrecer plan inmediatamente superior. Si tiene MOV-BASIC → MOV-PLUS ($299, 15GB).
  → Si pregunta por descuento en plan nuevo: MOV-PLUS con 20% = $239/mes por 3 meses.

RETENCIÓN: SOLO cuando el cliente dice explícitamente: "cancelar", "darme de baja", "portarme", "me voy con otra empresa".
  → Jerarquía: menos de 12 meses → RET-A (20% descuento plan actual), 12-24 meses → RET-B (upgrade gratis 6 meses), más de 24 meses → RET-C (upgrade con 30% descuento).
  → "No me convence", "está caro" NO son RETENCIÓN → MANEJO_OBJECION.

MANEJO_OBJECION: Cliente duda o rechaza una oferta SIN amenazar con cancelar.
  → Mostrar valor concreto, comparar alternativas, proponer plan de menor costo.
  → "¿Tiene descuento?" sobre plan NUEVO → precio del plan con 20% descuento.

OFERTA_ESPECIAL: Promociones para cerrar o retener cuando opciones estándar fueron rechazadas.

ESCALACIÓN: Cliente pide EXPLÍCITAMENTE hablar con supervisor. No usar por frustración general.

SOPORTE: Problema técnico activo. Resolver SIEMPRE antes de vender.

CIERRE: Cliente acepta claramente: "me gusta", "lo quiero", "me interesa", "suena bien", "¿cuánto sería?", "¿cómo lo activo?", "me quedo con ese".
  → Confirmar y proceder con activación inmediata.

ESPERAR: Todo lo demás. Fragmentos cortos, datos personales, monosílabos, saludos, silencios. ANTE LA DUDA → ESPERAR."""


def get_call_context(dynamodb_pk, current_segment_id, table_name=''):
    name = table_name or DYNAMODB_TABLE_NAME
    if not name or not dynamodb_pk:
        return ""
    try:
        table = dynamodb.Table(name)
        response = table.query(
            KeyConditionExpression=Key('PK').eq(dynamodb_pk),
            ScanIndexForward=False,
            Limit=MAX_CONTEXT_SEGMENTS * 3
        )
        segments = []
        for item in response.get('Items', []):
            if item.get('Channel') in ('CALLER', 'AGENT') and \
               item.get('SegmentId') != current_segment_id and item.get('Transcript'):
                role = 'Cliente' if item['Channel'] == 'CALLER' else 'Agente'
                sentiment = item.get('Sentiment', '')
                s = f" [{sentiment}]" if sentiment and sentiment not in ('NEUTRAL', '') else ''
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
        print(f"DynamoDB error: {e}")
        return ""


def query_knowledge_base(query):
    if not KNOWLEDGE_BASE_ID:
        return ""
    try:
        response = bedrock_agent.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': query},
            retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults': 3}}
        )
        return '\n\n'.join(
            r.get('content', {}).get('text', '')
            for r in response.get('retrievalResults', [])
            if r.get('content', {}).get('text', '')
        )
    except Exception as e:
        print(f"KB error: {e}")
        return ""


def detect_client_name(full_text):
    tl = full_text.lower()
    for name in DEMO_NAMES:
        if name.lower() in tl:
            return name
    return ""


def detect_current_plan(full_text):
    for plan in PLAN_PRICES:
        if plan.lower() in full_text.lower():
            return plan
    return ""


def calculate_discount_prices(plan_id):
    if plan_id not in PLAN_PRICES:
        return ""
    cp = PLAN_PRICES[plan_id]
    up = PLAN_UPGRADES.get(plan_id)
    lines = [f"Plan actual {plan_id} con 20% descuento: ${round(cp*0.80)}/mes por 3 meses (RET-A)"]
    if up and up in PLAN_PRICES:
        up_price = PLAN_PRICES[up]
        lines.append(f"Upgrade gratuito a {up} (${up_price}) por 6 meses (RET-B)")
        lines.append(f"{up} con 20% descuento: ${round(up_price*0.80)}/mes por 3 meses")
        lines.append(f"{up} con 30% descuento: ${round(up_price*0.70)}/mes por 3 meses (RET-C, alto valor)")
    return "\n".join(lines)


def get_personalized_context(transcript, call_context):
    results = []
    full_text = f"{call_context}\n{transcript}"
    tl = transcript.lower()
    ftl = full_text.lower()

    # Perfil del cliente
    name = detect_client_name(full_text)
    if name:
        profile = query_knowledge_base(f"perfil cliente {name} plan actual precio antigüedad consumo internet hogar lineas")
        if profile:
            results.append(f"PERFIL DEL CLIENTE (solo datos objetivos, no usar como script):\n{profile}")

    # Retención / cancelación / competencia
    if any(w in tl for w in ["cancelar", "baja", "portarme", "cambiarme", "otra empresa", "movistar", "at&t", "competencia"]):
        cat = query_knowledge_base("oferta retención descuento RET-A RET-B RET-C jerarquía antigüedad")
        if cat:
            results.append(f"OFERTAS DE RETENCIÓN:\n{cat}")
        plan = detect_current_plan(full_text)
        if plan:
            calc = calculate_discount_prices(plan)
            if calc:
                results.append(f"PRECIOS CALCULADOS PARA {plan}:\n{calc}")

    # Pregunta de descuento / precio
    elif any(w in tl for w in ["descuento", "más barato", "cuánto quedaría", "cuánto sería", "precio"]):
        plan = detect_current_plan(full_text)
        if plan:
            calc = calculate_discount_prices(plan)
            if calc:
                results.append(f"PRECIOS CON DESCUENTO:\n{calc}")
        cat = query_knowledge_base(f"planes precios descuento opciones {transcript}")
        if cat:
            results.append(f"CATÁLOGO:\n{cat}")

    # Upsell / gigas / datos — solo móvil si no mencionaron hogar
    elif any(w in tl for w in ["gigas", "datos", "paquetes", "roaming", "viaj"]):
        already_hogar = any(w in ftl for w in ["internet hogar", "plan hogar", "hog-", "internet_hogar"])
        q = f"plan móvil upgrade gigas datos opciones precio {transcript}" if not already_hogar else f"plan móvil upgrade gigas {transcript}"
        cat = query_knowledge_base(q)
        if cat:
            results.append(f"PLANES MÓVILES:\n{cat}")

    # Cross-sell hogar / bundle
    elif any(w in tl for w in ["internet", "hogar", "casa", "telmex", "izzi", "totalplay", "megacable", "axtel", "fibra"]):
        cat = query_knowledge_base("bundle internet hogar móvil ahorro precio planes hogar")
        if cat:
            results.append(f"BUNDLE MÓVIL + HOGAR:\n{cat}")

    # Plan familiar
    elif any(w in tl for w in ["familiar", "familia", "esposo", "esposa", "hijo", "hija", "líneas", "lineas"]):
        cat = query_knowledge_base("plan familiar múltiples líneas ahorro precio")
        if cat:
            results.append(f"PLANES FAMILIARES:\n{cat}")

    # Fallback
    else:
        cat = query_knowledge_base(transcript)
        if cat:
            results.append(f"INFORMACIÓN RELEVANTE:\n{cat}")

    return "\n\n".join(results)


def lambda_handler(event, context):
    print("Event:", json.dumps(event))

    tsa = event.get('transcript_segment_args', {})
    transcript = event.get('text', event.get('transcript', '')).strip()
    call_id = event.get('call_id', event.get('callId', event.get('CallId', '')))
    segment_id = event.get('segmentId', event.get('SegmentId', tsa.get('SegmentId', '')))
    is_partial = event.get('isPartial', event.get('IsPartial', tsa.get('IsPartial', False)))
    sentiment = event.get('sentiment', event.get('Sentiment', 'NEUTRAL'))

    if is_partial:
        return build_response('')
    if len(transcript.split()) < 4:
        return build_response('')

    dynamodb_pk = event.get('dynamodb_pk', f'c#{call_id}')
    table_name = event.get('dynamodb_table_name', DYNAMODB_TABLE_NAME)

    # Transcript segments always use trs# prefix regardless of orchestrator's pk
    transcript_pk = f'trs#{call_id}'
    context_text = get_call_context(transcript_pk, segment_id, table_name)
    kb_context = get_personalized_context(transcript, context_text)

    parts = []
    if kb_context:
        parts.append(kb_context)
    if context_text:
        parts.append(f"CONTEXTO DE LA LLAMADA:\n{context_text}")
    parts.append(f"ÚLTIMO MENSAJE DEL CLIENTE:\n{transcript}")
    parts.append(f"SENTIMIENTO: {sentiment}")
    parts.append("Responde con el JSON de la acción correcta.")

    user_message = '\n\n'.join(parts)

    try:
        response = bedrock.invoke_model(
            modelId='us.amazon.nova-lite-v1:0',
            body=json.dumps({
                'system': [{'text': SYSTEM_PROMPT}],
                'messages': [{'role': 'user', 'content': [{'text': user_message}]}],
                'inferenceConfig': {'maxTokens': 250, 'temperature': 0.1}
            })
        )
        result = json.loads(response['body'].read())
        text = result['output']['message']['content'][0]['text'].strip()

        # Strip markdown if model wraps response
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
            accion = parsed.get('accion', 'ESPERAR')
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


def build_response(message):
    return {'message': message}