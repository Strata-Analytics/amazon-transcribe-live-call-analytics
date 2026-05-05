import boto3
import json

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

SYSTEM_PROMPT = """Eres el copilot de un agente de contact center de telecomunicaciones en Latinoamérica.

Tu rol es analizar la conversación en tiempo real y cuando detectes una oportunidad o riesgo, 
generar UNA recomendación concreta y accionable para el agente humano.

Reglas:
- Responde SOLO si hay algo accionable. Si no hay nada relevante, responde con {"accion": "ESPERAR", "recomendacion": ""}
- Máximo 2 oraciones, directo al punto
- Siempre en español latinoamericano
- Formato JSON: {"accion": "TIPO", "recomendacion": "texto"}

Tipos de acción:
- RETENCIÓN: cliente quiere cancelar o menciona irse a la competencia
- UPSELL: cliente necesita más datos, menciona que se le acaba el plan
- OFERTA: oportunidad de ofrecer un plan mejor
- ESCALACIÓN: cliente muy enojado, pide supervisor
- ESPERAR: no hay acción necesaria ahora"""

def lambda_handler(event, context):
    print("Event received:", json.dumps(event))
    
    # Extraer datos del evento que manda el LCA
    transcript = event.get('text', '')
    call_id = event.get('call_id', '') 
    caller_sentiment = event.get('callerSentiment', 'NEUTRAL')
    agent_sentiment = event.get('agentSentiment', 'NEUTRAL')
    
    # Si no hay transcripción, no hacer nada
    if not transcript or len(transcript.strip()) < 10:
        return build_response('')
    
    # Solo actuar si hay sentimiento negativo del cliente o keywords críticos
    keywords = ['cancelar', 'darme de baja', 'baja', 'cambiarme', 
                'competencia', 'más gigas', 'mejor plan', 'caro',
                'cobro', 'supervisor', 'queja', 'enojado', 'molesto',
                'portabilidad', 'no funciona', 'pésimo', 'terrible']
    
    text_lower = transcript.lower()
    has_keyword = any(kw in text_lower for kw in keywords)
    is_negative = caller_sentiment in ['NEGATIVE', 'MIXED']
    
    if not has_keyword and not is_negative:
        return build_response('')
    
    # Invocar Bedrock
    prompt = f"""Contexto de la llamada:
{transcript}

Sentimiento del cliente: {caller_sentiment}
Sentimiento del agente: {agent_sentiment}

¿Qué debe hacer el agente ahora?"""

    try:
        response = bedrock.invoke_model(
            modelId='us.amazon.nova-lite-v1:0',
            body=json.dumps({
                'system': [{'text': SYSTEM_PROMPT}],
                'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
                'inferenceConfig': {'maxTokens': 200, 'temperature': 0.3}
            })
        )
        
        result = json.loads(response['body'].read())
        text = result['output']['message']['content'][0]['text']
        
        # Parsear el JSON de respuesta
        try:
            parsed = json.loads(text)
            accion = parsed.get('accion', 'ESPERAR')
            recomendacion = parsed.get('recomendacion', '')
            
            if accion == 'ESPERAR' or not recomendacion:
                return build_response('')
                
            return build_response(f"[{accion}] {recomendacion}")
        except:
            return build_response(text)
            
    except Exception as e:
        print(f"Error invoking Bedrock: {e}")
        return build_response('')

def build_response(message):
    return {
        'message': message,
        'status': 'success'
    }