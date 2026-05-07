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
| `CallAudioSource` | `Amazon Chime SDK Voice Connector (SIPREC)` | |
| `CallAudioProcessor` | `Amazon Chime SDK Call Analytics` | |
| `CustomVoiceConnectorId` | `bpma7dkadecjeiien6ohjn` | See Section 3 |
| `TranscribeApiMode` | `analytics` | Required for sentiment + categories |
| `TranscribeLanguageCode` | `es-US` | Spanish Latin America |
| `TranscribeLanguageOptions` | `en-US, es-US` | |
| `BedrockModelId` | `us.amazon.nova-lite-v1:0` | Main RT model |
| `SummaryBedrockModelId` | `us.amazon.nova-lite-v1:0` | Post-call summary |
| `AgentAssistOption` | `Bring your own AWS Lambda function` | See Section 2 |
| `AgentAssistExistingLambdaFunctionArn` | ARN of `lca-poc-agent-assist` | See Section 2 |
| `AgentAssistQnABotOpenSearchNodeCount` | `1` | Not used (QnABot disabled) |
| `EndOfCallTranscriptSummary` | `BEDROCK` | |
| `IsContentRedactionEnabled` | `true` | PII redaction |
| `EnableVoiceToneAnalysis` | `Enabled` | Voice tone from audio |
| `DynamoDbExpirationInDays` | `7` | |
| `AudioRecordingExpirationInDays` | `1` | |
| `CloudFrontPriceClass` | `PriceClass_100` | |
| `UseExistingVPC` | `false` | Stack creates its own VPC |
| `SiprecAllowedCidrList` | Your IP in CIDR format e.g. `X.X.X.X/32` | |

---

## 2. Lambda: Agent Assist (`lca-poc-agent-assist`)

This is the custom agent assist Lambda that replaces the QnABot. It receives
transcript segments in real-time and uses Amazon Bedrock (Nova Lite) to generate
NBO recommendations for the agent.

**Source code:** `lca-ai-stack/source/lambda_functions/strata_agent_assist/lambda_function.py`

### Create the Lambda:

```bash
aws lambda create-function \
  --function-name lca-poc-agent-assist \
  --runtime python3.12 \
  --role <YOUR_LAMBDA_EXECUTION_ROLE_ARN> \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lca-ai-stack/source/lambda_functions/strata_agent_assist/lambda_function.zip \
  --region us-east-1
```

### Permissions — attach Bedrock + DynamoDB access:

```bash
aws iam attach-role-policy \
  --role-name <LAMBDA_EXECUTION_ROLE_NAME> \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess

aws iam attach-role-policy \
  --role-name <LAMBDA_EXECUTION_ROLE_NAME> \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess
```

### Environment variables (optional — for DynamoDB context + KB RAG):

| Variable | Value | Purpose |
|---|---|---|
| `DYNAMODB_TABLE_NAME` | `lca-poc-copilot-AISTACK-...-EventSourcingTable-...` | Call history context (last 10 CALLER turns). If unset, skipped. |
| `KNOWLEDGE_BASE_ID` | Bedrock KB ID | Product catalog RAG. If unset, skipped. |

> The orchestrator also passes `dynamodb_table_name` and `dynamodb_pk` in the event payload — the Lambda uses these directly, so `DYNAMODB_TABLE_NAME` env var is only needed as fallback.

### Resource-based policy — allow LCA orchestrator to invoke:

```bash
# Get the ARN of the AsyncAgentAssistOrchestrator Lambda from the AISTACK nested stack
# Then add permission:
aws lambda add-permission \
  --function-name lca-poc-agent-assist \
  --statement-id allow-lca-orchestrator \
  --action lambda:InvokeFunction \
  --principal lambda.amazonaws.com \
  --source-arn <ARN_OF_AsyncAgentAssistOrchestr_LAMBDA> \
  --region us-east-1
```

The ARN of the orchestrator Lambda is visible in:
CloudFormation → `lca-poc-copilot` → AISTACK nested stack → Resources → `AsyncAgentAssistOrchestratorFunction`

### Critical: response format

The LCA orchestrator reads `payload["message"]` from this Lambda's response. The Lambda **must** return:

```python
def build_response(message):
    return {'message': message}   # key must be exactly 'message'
```

Any other key (e.g. `response`, `result`) causes a silent KeyError in the orchestrator — the bot panel shows nothing.

### Orchestrator payload format (Amazon Connect KVS)

When using the Amazon Connect KVS audio source, the orchestrator sends a **nested** payload — fields are NOT all at top level:

```json
{
  "text": "quiero cancelar mis servicios",
  "call_id": "e4b6caef-...",
  "transcript_segment_args": {
    "Channel": "AGENT_ASSISTANT",
    "IsPartial": false,
    "SegmentId": "...",
    ...
  },
  "dynamodb_table_name": "lca-poc-copilot-...-EventSourcingTable-...",
  "dynamodb_pk": "c#e4b6caef-..."
}
```

Key notes:
- `Channel` and `IsPartial` are nested inside `transcript_segment_args`, **not** top-level
- `dynamodb_pk` uses a `c#` prefix — use it directly for DynamoDB queries (do not use bare `call_id`)
- The orchestrator pre-filters: only CALLER, non-partial segments reach this Lambda
- `Channel` in `transcript_segment_args` is always `"AGENT_ASSISTANT"` (the write-back channel) — not the speaker channel

### Behavior

Every final CALLER segment (≥5 chars) is sent to Bedrock Nova Lite with:
- Last 10 CALLER utterances from DynamoDB as conversation context
- Relevant product catalog snippets from Bedrock Knowledge Base (if `KNOWLEDGE_BASE_ID` set)
- Current transcript and detected sentiment

Bedrock responds with JSON: `{"accion": "TYPE", "recomendacion": "text", "urgencia": "alta|media|baja"}`

Action types: `CROSS_SELL`, `UPSELL`, `RETENCIÓN`, `OFERTA_ESPECIAL`, `ESCALACIÓN`, `SOPORTE`, `CIERRE`, `ESPERAR`

When `accion == "ESPERAR"` or `recomendacion` is empty, Lambda returns `{"message": ""}` and nothing is shown in the UI (no-op). All other actions return `{"message": "[ACCION] recomendacion text"}`.

Test phrase: **"quiero cancelar mis servicios"** → should trigger `RETENCIÓN`, duration >500ms in logs.

---

## 3. Chime SDK Voice Connector

Used for SIPREC audio ingestion from any telephony platform.

### Create Voice Connector:

```bash
aws chime-sdk-voice create-voice-connector \
  --name lca-poc-voice-connector \
  --require-encryption \
  --aws-region us-east-1 \
  --region us-east-1
```

Note the `VoiceConnectorId` from the response — this goes in the CloudFormation parameter `CustomVoiceConnectorId`.

### Configure Termination:

```bash
aws chime-sdk-voice put-voice-connector-termination \
  --voice-connector-id <VOICE_CONNECTOR_ID> \
  --termination '{"CidrAllowedList":["YOUR_IP/32"],"CallingRegions":["US"],"Disabled":false}' \
  --region us-east-1
```

### Configure Streaming (KVS + EventBridge):

In AWS Console: Chime SDK → Voice Connectors → your connector → Streaming:
- Sending to Kinesis Video Streams: **Start**
- Data retention: **No**
- Streaming notification target: **EventBridge**
- Call analytics: **Activate** → select the media pipeline configuration created by the LCA stack
  (name format: `lca-poc-copilot-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

### Configure SIP Rule for PSTN Audio (two-channel calls):

> **PENDING — not working yet.** Under investigation. Do not include in production setup until resolved. Use the WebSocket client (Section 5) for demos.
>
> **What's been created:**
> - Lambda `lca-poc-pstn-handler` (Python 3.12) — answers inbound calls and holds with Pause actions
> - SIP Media Application `lca-poc-sip-app` → points to the Lambda
> - SIP Rule `lca-poc-sip-rule` → trigger type `RequestUriHostname`, trigger value `bpma7dkadecjeiien6ohjn.voiceconnector.chime.aws`
> - Resource-based policy on Lambda: **confirmed correct** — two statements present, both allow `voiceconnector.chime.amazonaws.com`
>
> **Known issue:** Lambda is never invoked when calling the assigned number (`+19105050858`).
>
> **Root cause hypothesis:** The phone number is assigned to the Voice Connector (SIP trunking), not the PSTN Audio service. For inbound PSTN calls to a Chime-provisioned number, the correct SIP Rule trigger type is `ToPhoneNumber`, not `RequestUriHostname`. The `RequestUriHostname` trigger fires when an external SIP trunk (e.g. a PBX) dials the Voice Connector hostname directly.
>
> **Blocker:** The phone number does not appear in the SIP Rule console dropdown because it is assigned to the Voice Connector rather than the PSTN Audio pool. To fix: unassign the number from the Voice Connector and reassign it under PSTN Audio, then create a `ToPhoneNumber` SIP Rule.

---

## 4. Stack Update — Disable QnABot, Enable Custom Lambda

After deploying the base stack, update it to replace QnABot with the custom Lambda:

In CloudFormation → `lca-poc-copilot` → Update Stack → Use existing template → change:

| Parameter | Old value | New value |
|---|---|---|
| `AgentAssistOption` | `QnABot on AWS with new Bedrock knowledge base` | `Bring your own AWS Lambda function` |
| `AgentAssistExistingLambdaFunctionArn` | (empty) | ARN of `lca-poc-agent-assist` |

> ⚠️ This update deletes the QnABot stack and OpenSearch domain. During the update you may get a `DELETE_FAILED` on `OpenSearchDashboardsRoleAttachment`. If so: go to the QnABot nested stack → Retry delete → select "Delete this stack but retain resources" → check `OpenSearchDashboardsRoleAttachmentRoleMapping` → Delete.

---

## 5. UI: Agent Assist Panel (right column)

**PENDING.**
The LCA UI only renders the right-side Agent Assist panel when `REACT_APP_ENABLE_LEX_AGENT_ASSIST=true` (Lex/QnABot mode). Since we use a custom Lambda, that panel was hidden. 

---

## 6. WebSocket Two-Channel Client

For demos requiring two separate audio channels (AGENT + CALLER), use the custom
WebSocket client at `tools/demo/speaksense-two-channel-client.html`.

### How to use:

1. Serve the file from a local HTTP server (required — `file://` URLs block microphone access):
```bash
cd tools/demo
python3 -m http.server 8080
```

2. Open `http://localhost:8080/speaksense-two-channel-client.html` in Chrome

3. Get a fresh Cognito token from the LCA panel:
   - Open `https://d2bub56hlp4ms3.cloudfront.net` and log in
   - DevTools → Network → WS → find `api/v1/ws?authorization=Bearer...`
   - Copy the full Request URL

4. Paste the URL into the WebSocket Endpoint field

5. Person 1 selects **AGENT**, generates a Call ID, shares it with Person 2

6. Person 2 selects **CALLER**, pastes the same Call ID

7. Both click **Iniciar Stream**

> The Cognito token expires after 1 hour. Refresh it by repeating step 3.

### How two-channel works (server side):

The LCA WebSocket transcriber was modified to accept two independent mono connections sharing the same `callId`. The `channel` field in the START message declares which role each connection represents. The server uses that to label the KDS event — no stereo audio or channel detection needed.

**START message format:**
```json
{ "callEvent": "START", "callId": "<shared-uuid>", "samplingRate": 16000, "channel": "CALLER" }
{ "callEvent": "START", "callId": "<shared-uuid>", "samplingRate": 16000, "channel": "AGENT" }
```

**Source changes:** `lca-websocket-transcriber-stack/source/app/src/lca.ts` (committed to repo)

### Redeploy after source changes:

Use the provided script from the repo root of `lca-websocket-transcriber-stack/`:

```bash
cd lca-websocket-transcriber-stack
./update-ecs.sh lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E
```

Prerequisites: Docker Desktop running, AWS CLI configured, `jq` installed (`brew install jq`).

The script builds the Docker image, pushes to ECR, registers a new ECS task definition, and forces redeployment (~5–10 min). No manual docker commands needed.

---

## 7. Amazon Connect KVS Integration (Demo Setup)

This section documents the migration from Chime SDK Voice Connector (SIPREC) to Amazon Connect Kinesis Video Streams as the audio ingestion source. This enables a full call center demo scenario: customer calls from a phone → human agent answers in Connect CCP → LCA shows real-time transcript and analytics.

### Why Connect KVS instead of Chime SIPREC

The Chime SIPREC path (Section 3) had a known blocker: the phone number `+19105050858` was assigned to the Voice Connector (SIP trunking), making it incompatible with the PSTN Audio SIP Rule trigger required for inbound calls. Rather than unblocking that path, the team migrated to Amazon Connect KVS, which provides native call center routing and a built-in softphone (CCP) for agents.

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
11. Agent Assist panel shows cross-sell recommendations (lca-poc-agent-assist Lambda)
12. Call ends → post-call summary generated by Bedrock Nova Lite
```

---

## 8. Key Resource Reference

| Resource | Name / ID |
|---|---|
| LCA Stack | `lca-poc-copilot` |
| CloudFront URL | `https://d2bub56hlp4ms3.cloudfront.net` |
| LCA WebSocket endpoint | `wss://d23to8673muyll.cloudfront.net/api/v1/ws` |
| Voice Connector ID | `bpma7dkadecjeiien6ohjn` |
| Agent Assist Lambda | `lca-poc-agent-assist` |
| PSTN Handler Lambda | `lca-poc-pstn-handler` |
| Kinesis Data Stream | `lca-poc-copilot-CallDataStream-USa6pDauvPOj` |
| Recordings S3 Bucket | `lca-poc-copilot-recordingsbucket-bksjjk1mahrc` |
| Bedrock Boto3 Bucket | `lca-poc-copilot-aistack-1y2o3j3-bedrockboto3bucket-7jnuw54gbzjv` |
| WebApp S3 Bucket | `lca-poc-copilot-aistack-1y2o3j3mdoh6r-webappbucket-ymag6ijlvdsm` |
| ECS Cluster | `lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E-TranscribingCluster-DxEpZpnugVEN` |
| ECS Service | `lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E-TranscriberWebsocketFargateService-5M2p6XZKpwGq` |
| ECR Repository | `lca-poc-copilot-websockettranscriberstack-2xznama9oh6e-transcriberecrrepository-vlzypquptihb` |
| WebSocket CF Stack | `lca-poc-copilot-WEBSOCKETTRANSCRIBERSTACK-2XZNAMA9OH6E` |
| AWS Region | `us-east-1` |
| AWS Account | `992382598036` |
| Connect Instance | `lca-demo-strata` |
| Connect Instance ARN | `arn:aws:connect:us-east-1:992382598036:instance/37d931e6-3ea0-4055-8f2c-591783bfaf05` |
| Connect Phone Number | `+1 407-537-3430` |
| Connect CCP URL | `https://lca-demo-strata.my.connect.aws/ccp-v2` |
| StartLCA Lambda | See CloudFormation → `lca-poc-copilot` → Outputs → `StartLCAFunctionName` |

---
