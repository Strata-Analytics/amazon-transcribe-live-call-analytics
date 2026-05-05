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

### Create the Lambda:

```bash
aws lambda create-function \
  --function-name lca-poc-agent-assist \
  --runtime python3.12 \
  --role <YOUR_LAMBDA_EXECUTION_ROLE_ARN> \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lca-ai-stack/source/lambda/strata_agent_assist/lambda_function.zip \
  --region us-east-1
```

**Source code:** `lca-ai-stack/source/lambda/strata_agent_assist/lambda_function.py`

### Permissions — attach Bedrock access:

```bash
aws iam attach-role-policy \
  --role-name <LAMBDA_EXECUTION_ROLE_NAME> \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
```

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

### Keyword/sentiment filter behavior

The Lambda only calls Bedrock when at least one of these is true:
- The transcript contains a configured trigger keyword (e.g. `cancelar`, `terrible`, `pésimo`)
- AWS Comprehend detects NEGATIVE sentiment

Neutral phrases with no keywords (e.g. "Hola", "Bien") return `{'message': ''}` in ~2ms without calling Bedrock. This is intentional. Test with a phrase like **"quiero cancelar mi servicio"** to confirm the full pipeline end-to-end.

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

## 7. Key Resource Reference

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

---
