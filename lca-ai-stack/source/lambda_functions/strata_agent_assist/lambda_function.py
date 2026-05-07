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

SYSTEM_PROMPT="""Eres el copilot inteligente de un agente de contact center de telecomunicaciones de TelcoStrata. 
Tu objetivo es analizar la transcripción de la llamada en tiempo real y sugerir la siguiente mejor acción (Next Best Action) basándote en el contexto y los catálogos de planes móviles, internet hogar y retención proporcionados.

REGLAS ESTRICTAS Y DE ANTI-ALUCINACIÓN:
1. Responde ÚNICAMENTE con un JSON válido. No incluyas saludos, markdown de bloques de código (```json) fuera del JSON, ni texto adicional.
2. NOMBRES FICTICIOS: NUNCA uses nombres de los ejemplos del CRM (como Carlos, María, Roberto, Ana, Jorge, Lucía) a menos que el cliente explícitamente se identifique con ese nombre en la transcripción actual.
3. CATÁLOGO REAL: Usa exclusivamente los nombres y precios de los catálogos (ej. MOV-PLUS a $299, HOG-100 a $499, RET-A).
4. REGLA DE "ESPERAR" (CRÍTICA): Si el cliente está proporcionando datos personales (números de teléfono, direcciones, nombres), respondiendo con monosílabos ("sí", "no", "ajá"), o el contexto es ambiguo, DEBES clasificar la acción como ESPERAR. No intentes adivinar el siguiente paso si el cliente solo está dictando información.
5. LONGITUD: La recomendación debe tener máximo 2 oraciones. Sé directo, usa español latinoamericano neutro.
6. No actúes sobre la primera mención de un tema si el cliente continúa hablando. Espera a que termine su pensamiento completo antes de recomendar.

PASOS DE ANÁLISIS (Usa el campo "razonamiento" en tu JSON para esto):
- Paso 1: Analiza qué acaba de decir el cliente. ¿Es solo información de rutina o expresa una necesidad/queja?
- Paso 2: Evalúa si hay una oportunidad clara según los catálogos.
- Paso 3: Determina la acción.

FORMATO DE RESPUESTA ESPERADO:
{
  "razonamiento": "Breve justificación de por qué se elige la acción basándose en el último mensaje",
  "accion": "TIPO_DE_ACCION",
  "recomendacion": "Texto concreto, usando IDs de planes y precios si aplica. Si la acción es ESPERAR, pon 'Escuchando al cliente.'",
  "urgencia": "alta|media|baja|ninguna"
}

TIPOS DE ACCIÓN PERMITIDOS:
- CROSS_SELL: Cliente de móvil necesita internet hogar (ej. Bundle HOG-100 + MOV-PLUS), o quiere sumar familiares (MOV-FAMILIAR).
- UPSELL: Cliente agota sus datos o viaja y necesita un plan superior (ej. pasar de MOV-BASIC a MOV-PLUS o MOV-PRO).
- RETENCIÓN: Cliente amenaza con cancelar o irse a la competencia. Usa la jerarquía RET-A, RET-B, RET-C según el valor del cliente.
- OFERTA_ESPECIAL: Descuentos o promociones específicas para cerrar o retener.
- ESCALACIÓN: Quejas formales, solicitudes de supervisor o enojo extremo.
- SOPORTE: Problemas técnicos (falta de señal, errores). Resolver SIEMPRE antes de vender.
- CIERRE: el cliente está listo para aceptar. Indicar al agente que proceda con la activación inmediata del plan en el sistema.
- ESPERAR: Información de rutina (ej. "Mi número es 55...", "Vivo en la calle..."), confirmaciones simples ("sí", "claro"), o silencios. ANTE LA DUDA, USA ESPERAR. Saludos iniciales ("Hola", "Buenos días", "Buenas tardes") son siempre ESPERAR."""


def get_call_context(dynamodb_pk: str, current_segment_id: str, table_name: str = '') -> str:
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
               item.get('SegmentId') != current_segment_id and \
               item.get('Transcript'):
                role = 'Cliente' if item['Channel'] == 'CALLER' else 'Agente'
                sentiment = item.get('Sentiment', '')
                sentiment_str = f" [{sentiment}]" if sentiment and sentiment not in ('NEUTRAL', '') else ''
                segments.append(f"{role}{sentiment_str}: {item['Transcript']}")
        segments.reverse()
        caller_count = 0
        filtered = []
        for seg in segments:
            filtered.append(seg)
            if seg.startswith('Cliente'):
                caller_count += 1
            if caller_count >= MAX_CONTEXT_SEGMENTS:
                break
        return '\n'.join(filtered)
    except Exception as e:
        print(f"Error reading DynamoDB context: {e}")
        return ""


def query_knowledge_base(query: str) -> str:
    if not KNOWLEDGE_BASE_ID:
        return ""
    try:
        response = bedrock_agent.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': query},
            retrievalConfiguration={
                'vectorSearchConfiguration': {'numberOfResults': 3}
            }
        )
        results = []
        for result in response.get('retrievalResults', []):
            content = result.get('content', {}).get('text', '')
            if content:
                results.append(content)
        return '\n\n'.join(results)
    except Exception as e:
        print(f"Error querying KB: {e}")
        return ""


def lambda_handler(event, context):
    print("Event:", json.dumps(event))

    # Orchestrator (Amazon Connect LCA) sends nested payload:
    # top-level: text, call_id, transcript_segment_args, dynamodb_pk, dynamodb_table_name
    # Orchestrator already filters: only CALLER, IsPartial=false segments reach us
    tsa = event.get('transcript_segment_args', {})

    transcript = event.get('text', event.get('transcript', '')).strip()
    call_id = event.get('call_id', event.get('callId', event.get('CallId', '')))
    segment_id = event.get('segmentId', event.get('SegmentId', tsa.get('SegmentId', '')))
    is_partial = event.get('isPartial', event.get('IsPartial', tsa.get('IsPartial', False)))
    sentiment = event.get('sentiment', event.get('Sentiment', 'NEUTRAL'))

    # Orchestrator already filters partials and non-CALLER — just guard transcript length
    if is_partial:
        return build_response('')
    if not transcript or len(transcript.strip()) < 5:
        return build_response('')

    # DynamoDB PK uses "c#" prefix in LCA (passed directly by orchestrator)
    dynamodb_pk = event.get('dynamodb_pk', f'c#{call_id}')
    table_name = event.get('dynamodb_table_name', DYNAMODB_TABLE_NAME)

    # Obtener contexto de la llamada desde DynamoDB
    context_text = get_call_context(dynamodb_pk, segment_id, table_name)

    # Consultar Knowledge Base con el transcript actual
    kb_context = query_knowledge_base(transcript)

    # Construir prompt
    parts = []

    if kb_context:
        parts.append(f"INFORMACIÓN DEL CATÁLOGO RELEVANTE:\n{kb_context}")

    if context_text:
        parts.append(f"CONTEXTO DE LA LLAMADA:\n{context_text}")

    parts.append(f"ÚLTIMO MENSAJE DEL CLIENTE:\n{transcript}")
    parts.append(f"SENTIMIENTO DETECTADO: {sentiment}")
    parts.append("¿Qué debe hacer el agente ahora?")

    user_message = '\n\n'.join(parts)

    try:
        response = bedrock.invoke_model(
            modelId='us.amazon.nova-lite-v1:0',
            body=json.dumps({
                'system': [{'text': SYSTEM_PROMPT}],
                'messages': [{'role': 'user', 'content': [{'text': user_message}]}],
                'inferenceConfig': {'maxTokens': 200, 'temperature': 0.2}
            })
        )
        result = json.loads(response['body'].read())
        text = result['output']['message']['content'][0]['text'].strip()

        try:
            parsed = json.loads(text)
            accion = parsed.get('accion', 'ESPERAR')
            recomendacion = parsed.get('recomendacion', '')
            urgencia = parsed.get('urgencia', 'baja')

            if accion == 'ESPERAR' or not recomendacion:
                return build_response('')

            return build_response(f"[{accion}] {recomendacion}", urgencia)
        except json.JSONDecodeError:
            if len(text) > 10 and '{' not in text:
                return build_response(text)
            return build_response('')

    except Exception as e:
        print(f"Bedrock error: {e}")
        return build_response('')


def build_response(message: str, urgencia: str = 'baja') -> dict:
    return {'message': message}