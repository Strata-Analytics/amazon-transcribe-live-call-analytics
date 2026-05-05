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

SYSTEM_PROMPT = """Eres el copilot de un agente de contact center de telecomunicaciones en Latinoamérica. Trabajas para un operador móvil en México.

Tu rol es analizar la conversación en tiempo real y generar recomendaciones concretas y accionables para el agente humano, basándote en el contexto completo de la llamada y el catálogo de productos disponible.

REGLAS ESTRICTAS:
- Responde SIEMPRE en JSON válido, sin texto adicional antes o después
- Si el cliente solo está dando información (nombre, número, dirección, confirmando datos), responde ESPERAR sin excepción
- Si el agente está hablando o hay silencio, responde ESPERAR
- En caso de duda, ESPERAR
- Máximo 2 oraciones en recomendacion, directo al punto
- Siempre en español latinoamericano neutro
- No inventes datos del cliente que no estén en la conversación
- Usa el catálogo de productos para dar recomendaciones específicas con nombres y precios reales

FORMATO DE RESPUESTA:
{"accion": "TIPO", "recomendacion": "texto concreto para el agente", "urgencia": "alta|media|baja"}

TIPOS DE ACCIÓN:
- CROSS_SELL: el cliente usa un servicio básico y hay oportunidad de ofrecerle algo adicional (ej: solo tiene voz y puede agregar datos, tiene móvil y puede agregar internet hogar)
- UPSELL: el cliente tiene un plan y puede beneficiarse de uno superior (más gigas, velocidad, roaming)
- RETENCIÓN: el cliente quiere cancelar, menciona irse a la competencia, o expresa insatisfacción fuerte
- OFERTA_ESPECIAL: oportunidad de retener o crecer con descuento o promoción específica
- ESCALACIÓN: el cliente está muy enojado, pide supervisor, o menciona queja formal
- SOPORTE: el cliente tiene un problema técnico — resolver antes de intentar cualquier venta
- CIERRE: el cliente está receptivo y listo para aceptar — empujar el cierre ahora
- ESPERAR: el cliente da información, el agente habla, no hay oportunidad clara, o situación ambigua. EN CASO DE DUDA, ESPERAR.

SEÑALES CLAVE:
Cross-sell: "solo tengo llamadas", "no uso internet en el celu", "mi familia también necesita", "pago internet aparte", "tengo Telmex/Izzi en casa"
Upsell: "se me acaban los gigas", "me quedé sin datos", "compro paquetes adicionales", "viajo a EEUU", "trabajo desde casa"
Retención: "quiero cancelar", "me voy a ir con", "me ofrecieron en otra compañía", "estoy pensando en cambiarme"
Cierre: "suena bien", "¿cuánto sería?", "¿cómo lo activo?", "me interesa", "¿y cuándo entra?"
Soporte: "no tengo señal", "no puedo llamar", "no me carga internet", "error en mi teléfono"
Esperar: "mi número es", "mi nombre es", "sí", "no", "ajá", "entiendo", "claro" """


def get_call_context(call_id: str, current_segment_id: str) -> str:
    if not DYNAMODB_TABLE_NAME:
        return ""
    try:
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key('PK').eq(call_id),
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

    transcript = event.get('transcript', '').strip()
    channel = event.get('channel', event.get('Channel', ''))
    sentiment = event.get('sentiment', event.get('Sentiment', 'NEUTRAL'))
    call_id = event.get('callId', event.get('CallId', ''))
    segment_id = event.get('segmentId', event.get('SegmentId', ''))
    is_partial = event.get('isPartial', event.get('IsPartial', True))

    # Solo procesar segmentos finales del CALLER
    if is_partial:
        return build_response('')
    if channel not in ('CALLER', 'AGENT_QUERY'):
        return build_response('')
    if not transcript or len(transcript.strip()) < 5:
        return build_response('')

    # Obtener contexto de la llamada desde DynamoDB
    context_text = get_call_context(call_id, segment_id)

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
    return {
        'response': message,
        'urgencia': urgencia,
        'status': 'success'
    }