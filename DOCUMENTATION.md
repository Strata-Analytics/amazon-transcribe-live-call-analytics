# DOCUMENTATION.md
# SpeakSense Copilot RT 

This document describes all AWS infrastructure changes made on top of the original
[amazon-transcribe-live-call-analytics](https://github.com/aws-samples/amazon-transcribe-live-call-analytics)
stack. 

---

- LCA stack name: `lca-poc-copilot`

---

## 1. Base LCA Stack Deployment

Deploy the main LCA stack from CloudFormation using the template in `lca-main.yaml`.

### Key parameters used (non-default values only):

| Parameter | Value | Notes |
|---|---|---|
| `CallAudioSource` | `Amazon Connect Kinesis Video Streams` | Migrated from Chime SIPREC — see Section 7 |
| `CallAudioProcessor` | `Amazon Chime SDK Call Analytics` | No impact on Connect KVS path |
| `CustomVoiceConnectorId` | `bpma7dkadecjeiien6ohjn` | Legacy — not used with Connect KVS |
| `ConnectInstanceArn` | `arn:aws:connect:us-east-1:992382598036:instance/37d931e6-3ea0-4055-8f2c-591783bfaf05` | See Section 7 |
| `TranscribeApiMode` | `analytics` | Required for sentiment + categories |
| `TranscribeLanguageCode` | `es-US` | Spanish Latin America |
| `TranscribeLanguageOptions` | `en-US, es-US` | |
| `BedrockModelId` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Main RT model (migrated from Nova Lite) |
| `SummaryBedrockModelId` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Post-call summary |
| `AgentAssistOption` | `Bring your own AWS Lambda function` | See Section 2 |
| `AgentAssistExistingLambdaFunctionArn` | ARN of `lca-poc-agent-assist` | See Section 2 |
| `AgentAssistQnABotOpenSearchNodeCount` | `1` | Not used (QnABot disabled) |
| `EndOfCallTranscriptSummary` | `BEDROCK` | |
| `IsContentRedactionEnabled` | `false` | Disabled for demo — names reach KB |
| `EnableVoiceToneAnalysis` | `Enabled` | Voice tone from audio |
| `DynamoDbExpirationInDays` | `7` | |
| `AudioRecordingExpirationInDays` | `1` | |
| `CloudFrontPriceClass` | `PriceClass_100` | |
| `UseExistingVPC` | `false` | Stack creates its own VPC |
| `SiprecAllowedCidrList` | Your IP in CIDR format e.g. `X.X.X.X/32` | |

---

## 2. Lambda: Agent Assist Inline (`lca-poc-agent-assist`)

Custom agent assist Lambda that replaces QnABot. Invoked on every final CALLER segment in real-time. Uses Claude Haiku 4.5 (via Bedrock `converse` API) to generate NBA recommendations shown inline in the transcript panel.

**Source code:** `lca-ai-stack/source/lambda_functions/strata_agent_assist/lambda_function.py`

### Create the Lambda:

```bash
aws lambda create-function \
  --function-name lca-poc-agent-assist \
  --runtime python3.12 \
  --role <YOUR_LAMBDA_EXECUTION_ROLE_ARN> \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_function.zip \
  --region us-east-1
```

### Permissions:

The execution role `lca-poc-agent-assist-role-yqrnrn4o` requires the following policies:

```bash
# Bedrock — model inference + KB retrieval
aws iam attach-role-policy \
  --role-name lca-poc-agent-assist-role-yqrnrn4o \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess

# LCA EventSourcing table — read call transcript context
aws iam put-role-policy \
  --role-name lca-poc-agent-assist-role-yqrnrn4o \
  --policy-name DynamoDBReadCallTranscripts \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":["dynamodb:Query","dynamodb:GetItem"],
      "Resource":"arn:aws:dynamodb:us-east-1:992382598036:table/lca-poc-copilot-AISTACK-1Y2O3J3MDOH6R-EventSourcingTable-3KHT1JCM1TUW"
    }]
  }'

# Telco product tables — read plans, clients, offers
aws iam put-role-policy \
  --role-name lca-poc-agent-assist-role-yqrnrn4o \
  --policy-name DynamoDBTelcoTables \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":["dynamodb:GetItem","dynamodb:Scan"],
      "Resource":[
        "arn:aws:dynamodb:us-east-1:992382598036:table/lca-poc-copilot-telco-clientes",
        "arn:aws:dynamodb:us-east-1:992382598036:table/lca-poc-copilot-telco-planes",
        "arn:aws:dynamodb:us-east-1:992382598036:table/lca-poc-copilot-telco-ofertas"
      ]
    }]
  }'

# Bedrock KB retrieval
aws iam put-role-policy \
  --role-name lca-poc-agent-assist-role-yqrnrn4o \
  --policy-name BedrockKBAccess \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":["bedrock:Retrieve","bedrock:RetrieveAndGenerate"],
      "Resource":"*"
    }]
  }'
```

> ⚠️ `dynamodb:Scan` on `lca-poc-copilot-telco-clientes` is required for client lookup by name (fallback when phone doesn't match). Without it, the Lambda fails silently and the client profile is not loaded.

### Environment variables:

| Variable | Value | Purpose |
|---|---|---|
| `DYNAMODB_TABLE_NAME` | `lca-poc-copilot-AISTACK-1Y2O3J3MDOH6R-EventSourcingTable-3KHT1JCM1TUW` | LCA call transcript context |
| `KNOWLEDGE_BASE_ID` | Bedrock KB ID | Semantic scripts/arguments retrieval |
| `MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model (overridable) |
| `TABLA_PLANES` | `lca-poc-copilot-telco-planes` | DynamoDB plans table |
| `TABLA_CLIENTES` | `lca-poc-copilot-telco-clientes` | DynamoDB clients table |
| `TABLA_OFERTAS` | `lca-poc-copilot-telco-ofertas` | DynamoDB retention offers table |

### Resource-based policy — allow LCA orchestrator to invoke:

```bash
aws lambda add-permission \
  --function-name lca-poc-agent-assist \
  --statement-id allow-lca-orchestrator \
  --action lambda:InvokeFunction \
  --principal lambda.amazonaws.com \
  --source-arn <ARN_OF_AsyncAgentAssistOrchestr_LAMBDA> \
  --region us-east-1
```

ARN visible in: CloudFormation → `lca-poc-copilot` → AISTACK nested stack → Resources → `AsyncAgentAssistOrchestratorFunction`

### Critical: response format

The LCA orchestrator reads `payload["message"]`. Lambda **must** return:

```python
def build_response(message):
    return {'message': message}  # key must be exactly 'message'
```

### Orchestrator payload format (Amazon Connect KVS)

```json
{
  "text": "quiero cancelar mis servicios",
  "call_id": "e4b6caef-...",
  "transcript_segment_args": {
    "Channel": "AGENT_ASSISTANT",
    "IsPartial": false,
    "SegmentId": "..."
  },
  "dynamodb_table_name": "lca-poc-copilot-...-EventSourcingTable-...",
  "dynamodb_pk": "c#e4b6caef-..."
}
```

Key notes:
- `dynamodb_pk` uses `c#` prefix — transcript segments are stored under `trs#` prefix
- Lambda must query `trs#{call_id}` to read transcript context, not the `c#` pk passed by orchestrator
- The orchestrator pre-filters: only CALLER, non-partial segments reach this Lambda

### Architecture overview

```
CALLER segment (final, ≥4 words or in CIERRE_CORTO set)
    │
    ├── get_call_context(trs#{call_id})          ← DynamoDB: last 10 CALLER/AGENT/AGENT_ASSISTANT turns
    │
    ├── resolve_cliente(event, transcript, context_text)
    │       ├── phone lookup → get_cliente(phone)      ← DynamoDB telco-clientes (GetItem)
    │       ├── extract_name_from_context()             ← regex on transcript + context
    │       ├── cross-validate name vs phone profile
    │       └── fallback: get_cliente_by_nombre()      ← DynamoDB telco-clientes (Scan)
    │
    ├── compute_insights(cliente, plan_data)      ← arithmetic: gap_gb, extra_cost_est, net_saving
    │
    ├── build_catalog_section()                   ← DynamoDB telco-planes (all plans, cached)
    ├── build_profile_section()                   ← structured client data + GAP framing
    ├── build_pricing_context()                   ← [A]/[B] table, bundle options, PRECIO DE CIERRE
    ├── build_familiar_context()                  ← PROMO DÚO + plan familiar options
    ├── compute_retencion_oferta()                ← RET-A/B/C with exact prices
    ├── get_relevant_scripts()                    ← KB single query (semantic scripts only)
    │
    └── bedrock.converse(SYSTEM_PROMPT + blocks)  ← Claude Haiku 4.5, maxTokens=300, temp=0.1
            │
            └── JSON {razonamiento, accion, recomendacion, urgencia}
                    │
                    └── build_response(f"[{accion}] {recomendacion}")
```

### Client identification flow

The Lambda identifies clients by cross-validating phone number with spoken name:

1. Extract phone from event (`CustomerPhoneNumber` field or LCA DynamoDB call record)
2. `GetItem` on `telco-clientes` by normalized phone (`+` and spaces stripped)
3. Extract name from transcript + context using regex patterns ("mi nombre es X", "soy X", etc.)
4. If name matches phone profile → `confirmado=True`
5. If name doesn't match → `Scan` by first name → use that profile
6. If no match → empty profile, model operates without client context
7. If phone found but name not yet spoken → `confirmado=False`, profile injected with `⚠ PERFIL NO CONFIRMADO` warning

> ⚠️ Phone normalization: `+52 55 1234 5678` → `525512345678`. DynamoDB keys must use the same format. Verify with: `aws dynamodb get-item --table-name lca-poc-copilot-telco-clientes --key '{"telefono":{"S":"525512345678"}}'`

### Module-level caches

Three dicts cache DynamoDB reads with 5-minute TTL to avoid redundant reads across warm Lambda invocations:

```python
_cliente_cache: dict = {}   # telefono  → (item, timestamp)
_plan_cache:    dict = {}   # plan_id   → (item, timestamp)
_oferta_cache:  dict = {}   # oferta_id → (item, timestamp)
```

First invocation of each call reads all 11 plans (warm: ~1200ms, cached: ~0ms).

### Short-segment bypass (CIERRE_CORTO)

Segments under 4 words are normally filtered before reaching Bedrock. Closing phrases bypass this filter:

```python
CIERRE_CORTO = {
    "dale", "activalo", "actívalo", "confirmado", "confirmo", "listo",
    "adelante", "sí dale", "dale sí", "lo activo", "lo quiero",
    "avancemos", "vamos", "perfecto sí", "sí confirmo", "sí activalo",
    "dale activalo", "dale actívalo", "sí listo", "listo dale",
    "muchas gracias", "gracias", "hasta luego", "chau", "adiós",
    "no eso es todo", "eso es todo", "no nada más", "nada más"
}
```

### Action types

`OPORTUNIDAD_VENTA` | `UPSELL` | `INFORMACION_ADICIONAL` | `RETENCIÓN` | `MANEJO_OBJECION` | `OFERTA_ESPECIAL` | `ESCALACIÓN` | `SOPORTE` | `CIERRE` | `ESPERAR`

When `accion == "ESPERAR"` or `recomendacion` is empty → returns `{"message": ""}` → nothing shown in UI.

### CloudWatch logging

Every invocation logs:
```
phone resolved: '525512345678'
cliente DDB: 525512345678 → nombre=Carlos Mendoza
cliente: Carlos Mendoza plan=MOV-BASIC confirmado=True
[PROMPT_BLOCKS] ['CATÁLOGO DE PLANES...', 'DATOS DEL CLIENTE:', ...]
[NBA] accion=UPSELL urgencia=alta
[NBA] razonamiento=...
[NBA] recomendacion=...
```

### Prompt version

Current prompt: **v3.1** — 22 few-shot examples, dynamic catalog from DynamoDB, PROMO DÚO, anti-loop rules, CIERRE_CORTO bypass, closing protocol script.

Key behaviors:
- Dynamic plan catalog injected per invocation from DynamoDB (not hardcoded in prompt)
- UPSELL: if GAP confirmed in profile, goes directly to offer without discovery question
- UPSELL: two-scenario framing [A] base diff / [B] vs real cost with packages
- UPSELL: `⚠ PRECIO DE CIERRE` injected in pricing context when closing keywords detected
- OPORTUNIDAD_VENTA familiar: PROMO DÚO for 2 lines ($538/3 months vs $598), MOV-FAMILIAR-3 for 3+
- OPORTUNIDAD_VENTA hogar: only activates when client explicitly mentions internet/hogar — never proactive
- RETENCIÓN: explore → RET-A → RET-B → RET-C hierarchy, strict no skip
- CIERRE: confirms discount price (not base price), closing protocol: "Muchas gracias por comunicarte con TelcoStrata, [nombre]. Que tengas un excelente día."
- Hogar/bundle and familiar offers never mixed in the same turn

### Latency profile (warm container)

| Turn | Duration | Notes |
|---|---|---|
| First segment of call | ~4.5–5.5s | Cold start 500ms + 11 DDB reads (~1200ms) + Bedrock (~2600ms) |
| Subsequent segments (cached) | ~2.5–3.5s | All DDB cached, only Bedrock + context query |

To reduce first-turn latency: enable **Provisioned Concurrency = 1** in Lambda console (eliminates cold start).

---

## 2b. Lambda: Agent Assist Chat Bot (`lca-poc-agent-assist-bot`)

Conversational Lambda for the right-side chat panel. Invoked on-demand when the agent clicks a button or types a question. Returns natural language text (not JSON).

**Source code:** `lca-ai-stack/source/lambda_functions/strata_agent_assist_bot/lambda_function_chat_bot.py`

**API Gateway endpoint:** `https://lxzjs277g6.execute-api.us-east-1.amazonaws.com/chat`

### Create the Lambda:

```bash
aws lambda create-function \
  --function-name lca-poc-agent-assist-bot \
  --runtime python3.12 \
  --role arn:aws:iam::992382598036:role/service-role/lca-poc-agent-assist-role-yqrnrn4o \
  --handler lambda_function_chat_bot.lambda_handler \
  --zip-file fileb://lambda_function_chat_bot.zip \
  --region us-east-1
```

Same role as `lca-poc-agent-assist` — already has Bedrock + DynamoDB permissions.

### Environment variables:

| Variable | Value |
|---|---|
| `DYNAMODB_TABLE_NAME` | `lca-poc-copilot-AISTACK-1Y2O3J3MDOH6R-EventSourcingTable-3KHT1JCM1TUW` |
| `KNOWLEDGE_BASE_ID` | Bedrock KB ID |

### API Gateway configuration:

- Protocol: HTTP API
- Route: `POST /chat`
- Integration: Lambda proxy (payload format 2.0)
- Stage: `$default` (auto-deploy enabled)
- CORS: Allow origin `https://d2bub56hlp4ms3.cloudfront.net`, methods `POST OPTIONS`, headers `Content-Type`

### Request format:

**Button action:**
```json
{"call_id": "<uuid>", "button_action": "SUMMARIZE_CURRENT_CALL"}
```

**Free text:**
```json
{"call_id": "<uuid>", "message": "pregunta del agente"}
```

### Available button actions:

| button_action | Description |
|---|---|
| `SUMMARIZE_CURRENT_CALL` | 3-bullet summary of call so far |
| `IDENTIFY_CURRENT_TOPIC` | One-sentence topic + intent |
| `SUGGEST_RETENTION_SCRIPT` | Specific retention script with real prices |
| `SUGGEST_UPSELL_SCRIPT` | Upsell/cross-sell script for current context |
| `SUGGEST_CLOSING_SCRIPT` | Closing phrase adapted to conversation |

### Response format:
```json
{"message": "texto en español listo para mostrar"}
```

> ⚠️ API Gateway HTTP sends body as string — Lambda parses `event['body']` with `json.loads()`.

> ⚠️ DynamoDB context uses `trs#{call_id}` prefix (same as inline Lambda).

---

## 3. DynamoDB — Telco Product Tables

Three new tables created alongside the LCA stack to support direct client/product lookups (replaces RAG-based profile retrieval).

### Tables

| Table | PK | Contents |
|---|---|---|
| `lca-poc-copilot-telco-clientes` | `telefono` (String, normalized E.164 without `+`) | 6 demo client profiles |
| `lca-poc-copilot-telco-planes` | `plan_id` (String) | All mobile + home plans + CONFIG#BUNDLE |
| `lca-poc-copilot-telco-ofertas` | `oferta_id` (String) | RET-A/B/C/D retention offers |

### Phone number format (critical)

Keys in `telco-clientes` must use normalized format — no `+`, no spaces, no dashes:

| Raw | Normalized (DynamoDB key) |
|---|---|
| `+52 55 1234 5678` | `525512345678` |
| `+1 617 675 4444` | `16176754444` |
| `+9165551234` | `9165551234` |

Load data using the files in `dynamo_clientes.json`, `dynamo_planes.json`, `dynamo_ofertas.json`. Verify normalization matches before loading.

### Special plan keys

| plan_id | Purpose |
|---|---|
| `CONFIG#BUNDLE` | Bundle discount config (`descuento_pct: 15`) |
| `CONFIG#PAQUETES` | Additional data package pricing (`precio_paquete_gb`) — optional, fallback is 30 MXN/GB |

### Loading data

```bash
# Example — load a single client
aws dynamodb put-item \
  --table-name lca-poc-copilot-telco-clientes \
  --item file://item_carlos.json \
  --region us-east-1
```

---

## 4. Chime SDK Voice Connector (Legacy)

> **Legacy — no longer used for audio ingestion.** Audio now enters via Amazon Connect KVS (Section 8). Voice Connector and associated PSTN configuration remain for reference.

### PSTN SIP Rule (not working):

> **PENDING.** Lambda `lca-poc-pstn-handler` is never invoked when calling the number.
> Root cause: phone number assigned to Voice Connector (SIP trunking), not PSTN Audio pool. Fix: reassign number to PSTN Audio, use `ToPhoneNumber` trigger type in SIP Rule instead of `RequestUriHostname`.

---

## 5. Stack Updates Applied

### Update 1 — Disable QnABot, enable custom Lambda:

| Parameter | Value |
|---|---|
| `AgentAssistOption` | `Bring your own AWS Lambda function` |
| `AgentAssistExistingLambdaFunctionArn` | ARN of `lca-poc-agent-assist` |

> ⚠️ Deletes QnABot + OpenSearch. If `DELETE_FAILED` on `OpenSearchDashboardsRoleAttachment`: retry delete → "retain resources" → check `OpenSearchDashboardsRoleAttachmentRoleMapping`.

### Update 2 — Migrate audio to Amazon Connect KVS:

| Parameter | Value |
|---|---|
| `CallAudioSource` | `Amazon Connect Kinesis Video Streams` |
| `ConnectInstanceArn` | `arn:aws:connect:us-east-1:992382598036:instance/37d931e6-...` |

### Update 3 — Disable PII redaction:

| Parameter | Value |
|---|---|
| `IsContentRedactionEnabled` | `false` |

Disabled for demo so client names arrive unredacted and profile lookup by name works.

### Update 4 — Migrate model from Nova Lite to Claude Haiku 4.5:

| Parameter | Value |
|---|---|
| `BedrockModelId` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `SummaryBedrockModelId` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |

Also set as `MODEL_ID` env var in `lca-poc-agent-assist`. Nova Lite was replaced due to inconsistent instruction-following (hallucinated plan names, ignored retention hierarchy, used placeholder `[Nombre del Cliente]`).

---

## 6. UI: Agent Assist Panel

**PENDING — frontend dev task.**

Three changes needed in `CallPanel.jsx`:

1. **Line ~855** — `getAgentAssistPanel()`: add branch for `REACT_APP_ENABLE_LAMBDA_AGENT_ASSIST === 'true'` that renders the custom panel using `agentAssistSegments` (filter by `Channel === 'AGENT_ASSISTANT'`, use latest segment).
2. **Line ~964** — grid layout: extend 8/4 column split condition to include Lambda case.
3. **Line ~1033** — call site: verify `agentAssistSegments` is passed correctly.

**CodeBuild env var required:**
```
REACT_APP_ENABLE_LAMBDA_AGENT_ASSIST = true
REACT_APP_ENABLE_LEX_AGENT_ASSIST = false
```

**Deploy process:**
```bash
# Build
set CI=false && npx react-scripts build   # Windows
npm run build                              # Mac/Linux

# Deploy
aws s3 sync build/ s3://lca-poc-copilot-aistack-1y2o3j3mdoh6r-webappbucket-ymag6ijlvdsm --delete
aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"
```

---

## 7. WebSocket Two-Channel Client

For demos using browser audio instead of Connect. File: `tools/demo/speaksense-two-channel-client.html`

```bash
cd tools/demo && python3 -m http.server 8080
```

Open `http://localhost:8080/speaksense-two-channel-client.html`

Get fresh Cognito token: LCA panel → DevTools → Network → WS → copy Request URL with `?authorization=Bearer...`

Person 1: select **AGENT**, generate Call ID, share with Person 2.  
Person 2: select **CALLER**, paste Call ID.  
Both click **Iniciar Stream**.

> Token expires after 1 hour. Refresh from LCA panel DevTools.

**START message format:**
```json
{"callEvent": "START", "callId": "<shared-uuid>", "samplingRate": 16000, "channel": "CALLER"}
```

**Redeploy ECS after source changes:**
```bash
cd lca-websocket-transcriber-stack
./update-ecs.sh lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E
```

---

## 8. Amazon Connect KVS Integration (Demo Setup)

This section documents the migration from Chime SDK Voice Connector (SIPREC) to Amazon Connect Kinesis Video Streams as the audio ingestion source. This enables a full call center demo scenario: customer calls from a phone → human agent answers in Connect CCP → LCA shows real-time transcript and analytics.

### Why Connect KVS instead of Chime SIPREC

The Chime SIPREC path (Section 4) had a known blocker: the phone number was assigned to the Voice Connector (SIP trunking), making it incompatible with the PSTN Audio SIP Rule trigger required for inbound calls. Rather than unblocking that path, the team migrated to Amazon Connect KVS, which provides native call center routing and a built-in softphone (CCP) for agents.

### Stack Update

In CloudFormation → `lca-poc-copilot` → Update Stack → Use existing template, the following parameters were changed:

| Parameter | Old value | New value |
|---|---|---|
| `CallAudioSource` | `Amazon Chime SDK Voice Connector (SIPREC)` | `Amazon Connect Kinesis Video Streams` |
| `ConnectInstanceArn` | (empty) | `arn:aws:connect:us-east-1:992382598036:instance/37d931e6-3ea0-4055-8f2c-591783bfaf05` |

> Note: `CallAudioProcessor` remains `Amazon Chime SDK Call Analytics` — this parameter only affects the Chime stack and has no impact on the Connect KVS path.

This update deploys the `CONNECTKVSSTACK` nested stack and removes `CHIMEVCSTACK`.

### Amazon Connect Instance

| Field | Value |
|---|---|
| Instance alias | `lca-demo-strata` |
| Instance ARN | `arn:aws:connect:us-east-1:992382598036:instance/37d931e6-3ea0-4055-8f2c-591783bfaf05` |
| Region | `us-east-1` |
| Admin user | `sofia` (`sofia.perini@strata-analytics.us`) |
| Access URL | `https://lca-demo-strata.my.connect.aws` |
| CCP URL | `https://lca-demo-strata.my.connect.aws/ccp-v2` |

### Connect Instance Configuration

**Data streaming** (Contact Trace Records + Agent Events):
- Type: Kinesis Stream
- Stream: `lca-poc-copilot-CallDataStream-USa6pDauvPOj` (same stream used by LCA stack)

**Live Media Streaming** (KVS audio):
- Prefix: `lca`
- Retention: No retention (audio is saved to S3 by LCA after processing)

### Phone Number

| Field | Value |
|---|---|
| Number | `+1 407-537-3430` |
| Country | United States |
| Type | DID |
| Purpose | Demo and testing (calls from Argentina via VoIP app e.g. Skype) |
| Assigned contact flow | `LCA-EXAMPLE` (imported from `lca-connect-kvs-stack/lca-contact-flow.json`) |

### Lambda Authorization

The `StartLCA` Lambda (deployed by `CONNECTKVSSTACK`) must be authorized in Connect before it can be invoked from a contact flow:

Connect Console → `lca-demo-strata` → **Flows → AWS Lambda** → search `StartLCA` → **Add Lambda Function**

The function name is available in CloudFormation → `lca-poc-copilot` → **Outputs → `StartLCAFunctionName`**.

### Contact Flow Setup

1. Import `lca-connect-kvs-stack/lca-contact-flow.json` into Connect
2. Edit block **"Start LCA"** → set Function ARN to `StartLCA` Lambda
3. Edit block **"Set working queue"** → select `BasicQueue`
4. Save and Publish
5. Assign to phone number `+1 407-537-3430`

### Demo Flow

```
1. Agent opens CCP at lca-demo-strata.my.connect.aws/ccp-v2 → sets status to Available
2. Customer calls +1 407-537-3430 (from Argentina: use Skype or any VoIP app)
3. Agent answers in CCP
4. Contact flow starts media streaming → audio flows to KVS
5. StartLCA Lambda invoked → CallTranscriberFunction starts consuming KVS
6. Audio streamed to Amazon Transcribe (es-US, analytics mode)
7. Transcription events → Kinesis Data Stream → LCA AI Stack
8. LCA Web UI (CloudFront) → Calls → call appears "In Progress"
9. Real-time transcript separated by CALLER / AGENT
10. Sentiment analysis updated every few seconds
11. Agent Assist panel shows recommendations (lca-poc-agent-assist Lambda)
12. Call ends → post-call summary generated by Claude Haiku 4.5
```

---

## 9. Bedrock Knowledge Base (`speaksense-telco-kb`)

Used for semantic retrieval of agent scripts and argumentarios only. Exact prices, rules, and client profiles are now in DynamoDB (Section 3) — the KB is no longer the source of truth for those.

**S3 bucket:** `s3://speaksense-demo-knowledge-base/telco-data/`  
**Embeddings:** Titan Text Embeddings V2  
**Vector store:** Amazon S3 Vectors (no OpenSearch, no fixed cost)

### Files:

| File | Contents |
|---|---|
| `kb_planes_descripcion.json` | Plan descriptions and upsell arguments (semantic only — prices from DynamoDB) |
| `kb_ofertas_retencion_scripts.json` | Retention offer scripts and language (rules from DynamoDB) |

> Previous files (`planes_movil.json`, `planes_hogar.json`, `clientes_demo.json`, etc.) replaced by DynamoDB tables. KB is now queried only for semantic script/argument content — one query per invocation, highest-priority signal wins.

### Sync after updating files:

```bash
aws s3 cp <file> s3://speaksense-demo-knowledge-base/telco-data/<file>
```

Then: Bedrock → Knowledge Bases → `speaksense-telco-kb` → Data source → **Sync**

> To disable KB queries (reduces latency ~200-400ms): set `KNOWLEDGE_BASE_ID` env var to empty string in `lca-poc-agent-assist`.

---

## 10. Call Summary

### Custom Prompts

Stored in DynamoDB — accessible via CloudFormation → `lca-poc-copilot` → Outputs → `LLMCustomPromptSummaryTemplate`.

Edit the item `CustomSummaryPromptTemplates` with these attributes (no Markdown/asterisks — renders as plain text in UI):

**`1#SUMMARY`:** 
```
La siguiente es la transcripción de una llamada de contact center de TelcoStrata entre un agente y un cliente.
<transcript>{transcript}</transcript>
<agent_assistant_recommendations>{agent_assistant}</agent_assistant_recommendations>
Escribe un resumen en español que incluya: (1) el motivo real de la llamada, (2) qué planes o descuentos se mencionaron con sus precios exactos — si las recomendaciones del asistente difieren de lo que el agente dijo, priorizar los precios de las recomendaciones del asistente como referencia, (3) el resultado final: si el cliente aceptó, rechazó, o quedó pendiente. No uses nombres propios del cliente.
```

**`2#DETAILS`:** Returns one of: `CANCELACIÓN` | `UPSELL` | `OPORTUNIDAD VENTA` | `SOPORTE TÉCNICO` | `CONSULTA FACTURA` | `RETENCIÓN` | `CONSULTA PLAN` | `OTRO`

**`3#ACTIONS`:** NBO Ofrecido (plan name + exact price from agent_assistant_recommendations), NBO Aceptado (Sí/No/Pendiente), Resultado (RESUELTO/PENDIENTE/ESCALADO/CANCELACIÓN_PROCESADA/SIN_RESOLUCIÓN), Próxima acción (specific action, no generic phrases), Owner: AGENTE, Fecha: TBD.

### Including AGENT_ASSISTANT turns in summary

The summarization Lambda can be modified to include copilot recommendations as additional context. In the summarization Lambda, after fetching the transcript, build a second string from `AGENT_ASSISTANT` segments and replace `{agent_assistant}` in the prompt:

```python
agent_assistant_turns = [
    item['Transcript'] 
    for item in segments 
    if item.get('Channel') == 'AGENT_ASSISTANT' and item.get('Transcript')
]
agent_assistant_text = '\n'.join(agent_assistant_turns) if agent_assistant_turns else 'Sin recomendaciones registradas.'
prompt = prompt.replace('{agent_assistant}', agent_assistant_text)
```

> This requires the summarization Lambda's execution role to have `dynamodb:Query` on the EventSourcing table (already granted).

---

## 11. Transcribe Call Analytics — Custom Categories

7 categories created in Transcribe → Call Analytics → Categories. All trigger on CALLER channel.

| Category | Keywords |
|---|---|
| `INTENCION_CANCELAR` | cancelar, darme de baja, baja voluntaria, cambiarme |
| `MENCION_COMPETENCIA` | Movistar, AT&T, me ofrecieron, otra compañía |
| `CLIENTE_INSATISFECHO` | queja formal, supervisor, terrible, pésimo, es un abuso |
| `OPORTUNIDAD_UPSELL` | sin gigas, sin datos, compro paquetes, se me acaba, me quedé sin |
| `CIERRE_POSITIVO` | me interesa, lo quiero, cómo lo activo, suena bien, me quedo |
| `CLIENTE_RELLAMADOR` | ya llamé, llamé antes, ya contacté, no es la primera vez, ya hablé con |
| `OPORTUNIDAD_FAMILIAR` | agregar línea, plan familiar, línea para mi esposo, línea para mi hijo |

> Categories appear in the Call Categories panel in real-time. They also feed into the Call Summary DETAILS field.
> Note: `MENCION_COMPETENCIA` fires on general conversation words — this is a Transcribe category limitation, not a copilot bug.

---

## 12. Cost Management

Resources with idle cost:

| Resource | ~Cost/day idle | Action |
|---|---|---|
| NAT Gateway (VPC) | ~$1.20 | Cannot stop without destroying stack |
| ECS Service (WebSocket) | ~$0.25 | Set desired tasks to 0 when not in use |
| AppSync | ~$0.50 | Scales to zero automatically |
| OpenSearch | **Deleted** | Removed in Stack Update 1 |

**Pause ECS when not in use:**
```bash
aws ecs update-service \
  --cluster lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E-TranscribingCluster-DxEpZpnugVEN \
  --service lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E-TranscriberWebsocketFargateService-5M2p6XZKpwGq \
  --desired-count 0 --region us-east-1

# Resume:
# --desired-count 1
```

---

## 13. Key Resource Reference

| Resource | Name / ID |
|---|---|
| LCA Stack | `lca-poc-copilot` |
| CloudFront URL | `https://d2bub56hlp4ms3.cloudfront.net` |
| LCA WebSocket endpoint | `wss://d23to8673muyll.cloudfront.net/api/v1/ws` |
| Voice Connector ID | `bpma7dkadecjeiien6ohjn` (legacy) |
| Agent Assist Inline Lambda | `lca-poc-agent-assist` |
| Agent Assist Inline Role | `lca-poc-agent-assist-role-yqrnrn4o` |
| Agent Assist Bot Lambda | `lca-poc-agent-assist-bot` |
| Agent Assist Bot API | `https://lxzjs277g6.execute-api.us-east-1.amazonaws.com/chat` |
| PSTN Handler Lambda | `lca-poc-pstn-handler` (pending) |
| Kinesis Data Stream | `lca-poc-copilot-CallDataStream-USa6pDauvPOj` |
| Recordings S3 Bucket | `lca-poc-copilot-recordingsbucket-bksjjk1mahrc` |
| Bedrock Boto3 Bucket | `lca-poc-copilot-aistack-1y2o3j3-bedrockboto3bucket-7jnuw54gbzjv` |
| WebApp S3 Bucket | `lca-poc-copilot-aistack-1y2o3j3mdoh6r-webappbucket-ymag6ijlvdsm` |
| ECS Cluster | `lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E-TranscribingCluster-DxEpZpnugVEN` |
| ECS Service | `lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E-TranscriberWebsocketFargateService-5M2p6XZKpwGq` |
| ECR Repository | `lca-poc-copilot-websockettranscriberstack-2xznama9oh6e-transcriberecrrepository-vlzypquptihb` |
| WebSocket CF Stack | `lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E` |
| Knowledge Base | `speaksense-telco-kb` |
| KB S3 Bucket | `speaksense-demo-knowledge-base` |
| DynamoDB — LCA Transcripts | `lca-poc-copilot-AISTACK-1Y2O3J3MDOH6R-EventSourcingTable-3KHT1JCM1TUW` |
| DynamoDB — Telco Clientes | `lca-poc-copilot-telco-clientes` |
| DynamoDB — Telco Planes | `lca-poc-copilot-telco-planes` |
| DynamoDB — Telco Ofertas | `lca-poc-copilot-telco-ofertas` |
| AWS Region | `us-east-1` |
| AWS Account | `992382598036` |
| Connect Instance | `lca-demo-strata` |
| Connect Instance ARN | `arn:aws:connect:us-east-1:992382598036:instance/37d931e6-3ea0-4055-8f2c-591783bfaf05` |
| Connect Phone Number | `+1 407-537-3430` |
| Connect CCP URL | `https://lca-demo-strata.my.connect.aws/ccp-v2` |
| StartLCA Lambda | See CloudFormation → `lca-poc-copilot` → Outputs → `StartLCAFunctionName` |

---

## 14. Troubleshooting

**Agent assist shows nothing in panel**
→ Check `IS_LAMBDA_AGENT_ASSIST_ENABLED=true` in AsyncAgentAssistOrchestrator Lambda env vars.
→ Check CloudWatch logs of `lca-poc-agent-assist` — if no logs, orchestrator is not invoking it.
→ Verify `build_response` returns `{'message': message}` — not `{'response': ...}`.

**Agent assist shows nothing but CloudWatch has `[NBA] accion=ESPERAR`**
→ Normal behavior — ESPERAR returns empty string to UI. Check razonamiento to understand why model chose to wait.

**Client profile not loading (all turns show `cliente: ? plan=`)**
→ Check CloudWatch for `DDB scan by nombre error: AccessDeniedException`. If present: add `dynamodb:Scan` permission to `lca-poc-agent-assist-role-yqrnrn4o` on `lca-poc-copilot-telco-clientes`.
→ Check phone normalization: the key in DynamoDB must match the normalized phone (no `+`, no spaces). Verify with: `aws dynamodb get-item --table-name lca-poc-copilot-telco-clientes --key '{"telefono":{"S":"525512345678"}}'`
→ If `cliente DDB: <phone> → nombre=?`: the item exists but `nombre` field is empty. Fix the item in DynamoDB.

**Copilot confirms wrong price at CIERRE (e.g. $449 instead of $239)**
→ DynamoDB write lag: the copilot's previous turn (with the discount offer) wasn't persisted yet when the closing segment arrived. The `⚠ PRECIO DE CIERRE` line in the pricing context mitigates this, but it only appears when closing keywords (`activalo`, `dale`, etc.) are in the segment. Verify `CIERRE_CORTO` set includes the phrase used.

**Agent assist bot returns "No recibí ninguna pregunta"**
→ API Gateway HTTP sends body as string. Lambda must parse `event['body']` with `json.loads()`.

**Context not being used in recommendations**
→ Lambda reads `c#{call_id}` for the call record but transcript segments are under `trs#{call_id}`. Verify `get_call_context` uses `trs#{call_id}` prefix.

**Call categories not appearing**
→ With Connect KVS, categories require Contact Lens real-time enabled in the Contact Flow. Add/verify "Set recording and analytics behavior" block with Contact Lens RT enabled.

**`MENCION_COMPETENCIA` fires on normal conversation**
→ Known Transcribe category behavior — keywords are broad. Not a copilot bug. Narrow the category keywords in Transcribe → Call Analytics → Categories if needed.

**Stream Audio not creating a call in the panel**
→ ECS service may have 0 running tasks. Check ECS → Clusters → Services → Running count. Set desired count to 1.

**WebSocket connection fails immediately**
→ Cognito token expired. Get fresh token from LCA panel DevTools → Network → WS.

**First copilot response takes 5+ seconds**
→ Expected on cold start: Python init (~500ms) + 11 DDB reads (~1200ms) + Bedrock (~2600ms). Enable Provisioned Concurrency = 1 in Lambda console to eliminate cold start. Subsequent turns are ~2.5–3.5s.

**CloudFormation UPDATE_ROLLBACK_FAILED**
→ Stack actions → Continue update rollback → add failing resource to "Resources to skip".

**OpenSearch DELETE_FAILED during stack update**
→ QnABot nested stack → Retry → "Delete but retain" → check `OpenSearchDashboardsRoleAttachmentRoleMapping`.

**Call summary shows "Not available"**
→ Call was too short (< 30 seconds) or `CustomSummaryPromptTemplates` item not saved correctly in DynamoDB.

**"€" symbol instead of "$" in transcription**
→ Transcribe STT interpreting "pesos" as euro symbol. Ask demo participants to say "pesos" explicitly or "$X pesos".