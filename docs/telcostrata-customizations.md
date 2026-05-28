# TelcoStrata LCA Customizations

This document records every personalization applied to the Amazon Live Call Analytics (LCA) base platform to turn it into **TelcoStrata Agent Copilot** — a real-time AI assistant for telecom customer service agents.

---

## 1. Product Identity

| Item | Value |
|------|-------|
| Product name | **TelcoStrata Agent Copilot** |
| Base platform | [Amazon Live Call Analytics (LCA)](https://github.com/aws-samples/amazon-transcribe-live-call-analytics) v0.9.7 |
| Strata repository | `Strata-Analytics/amazon-transcribe-live-call-analytics` (fork) |
| Active branch | `develop` |

---

## 2. Environments

Two independent AWS deployments share the same codebase. Parameters differ per environment.

| Parameter | Dev | Demo |
|-----------|-----|------|
| AWS Account | `637423400532` | `992382669018` |
| Stack name | `agent-copilot-dev` | `agent-copilot-poc` |
| Region | `us-east-1` | `us-east-1` |
| Connect instance ARN | `…/7776ccd7-413b-4f5f-8638-988862559271` | `…/37d931e6-3ea0-4055-8f2c-591783bfaf05` |
| SIPREC allowed CIDR | `190.210.32.166/32` | `190.210.36.16/32` |
| Transcription engine | Deepgram Nova-3 | AWS Transcribe (analytics) |
| Agent assist Lambda | `agent-copilot-dev-agent-assist` | `agent-copilot-poc-agent-assist` |

Configuration files:
- Dev: `strata-deploy-to-dev/lca-stack-parameters-dev.json`
- Demo: `strata-deploy-to-dev/lca-stack-parameters.json`

---

## 3. Transcription Engine — Deepgram Nova-3 (Dev)

The dev environment replaces AWS Transcribe with [Deepgram Nova-3](https://deepgram.com).

### Why

| | AWS Transcribe Call Analytics | Deepgram Nova-3 |
|--|--|--|
| Price (real-time) | $0.030 / min | $0.0077 / min |
| 5-min call cost | ~$0.150 | ~$0.043 |
| Savings | — | **71% less** |
| Spanish accuracy | Good | Better (nova-3 es-419) |

### How it works

`TranscribeApiMode=deepgram` in CloudFormation parameters activates the Deepgram code path in the WebSocket/ECS Fargate transcriber (`lca-websocket-transcriber-stack/source/app/src/lca.ts`). A `startDeepgram()` function:

1. Connects to Deepgram with multichannel mode (2 channels: CALLER=`ch_0`, AGENT=`ch_1`)
2. Streams PCM audio chunks from the browser WebSocket
3. Converts Deepgram transcript events into the same `TranscriptEvent` shape that AWS Transcribe would produce
4. Writes `ADD_TRANSCRIPT_SEGMENT` events to Kinesis Data Stream — downstream services are unaffected

### Configuration

| CFN parameter | Value |
|---------------|-------|
| `TranscribeApiMode` | `deepgram` |
| `TranscriberEngine` | `deepgram` |
| `DeepgramApiKey` | stored as GitHub Secret `DEEPGRAM_API_KEY`, injected at deploy time |
| `DeepgramKeywords` (keytterm boost) | `Mov Pro:2, Mov Unlimited:2, TelcoStrata:2, telcoestrata.5g:3` |

### Deepgram options

```typescript
model: 'nova-3'
language: 'es-419'      // Latin-American Spanish
punctuate: true
interim_results: true
endpointing: 150        // ms of silence before finalizing (reduced from 300 for lower latency)
encoding: 'linear16'
sample_rate: 44100      // browser microphone
channels: 2
multichannel: true
```

### Duplicate-segment deduplication

Deepgram can re-segment mid-utterance (sends a new `start` time for the same speech). A per-channel `activeStartTime` tracker locks the `SegmentId` to the first start time seen for each utterance, preventing duplicate lines in the UI.

### Files changed

| File | Change |
|------|--------|
| `lca-websocket-transcriber-stack/source/app/src/lca.ts` | Added `startDeepgram()` function |
| `lca-websocket-transcriber-stack/source/app/package.json` | Added `@deepgram/sdk: ^3.13.0` |
| `lca-websocket-transcriber-stack/source/app/Dockerfile` | Upgraded Node 16 → 18 |
| `lca-websocket-transcriber-stack/deployment/lca-websocket-transcriber.yaml` | Added `DeepgramApiKey`, `DeepgramKeywords` params + ECS env vars |
| `lca-main.yaml` | Added `deepgram` to `TranscribeApiMode` AllowedValues; passes Deepgram params to sub-stacks |
| `strata-deploy-to-dev/lca-stack-parameters-dev.json` | Set `TranscribeApiMode=deepgram`, `DeepgramKeywords` |
| `.github/workflows/deploy-dev.yml` | Injects `DEEPGRAM_API_KEY` secret into CloudFormation deploy; builds Docker image in CI |

---

## 4. Language Configuration

All transcription and AI responses are tuned for **Latin-American Spanish**.

| Parameter | Value | Notes |
|-----------|-------|-------|
| `TranscribeLanguageCode` | `es-US` | Primary language |
| `TranscribePreferredLanguage` | `es-US` | Preferred in multi-language detection |
| `TranscribeLanguageOptions` | `en-US, es-US` | Fallback to English if needed |
| Deepgram language | `es-419` | Latin-American Spanish (Nova-3) |
| Comprehend language | `es` | Sentiment analysis in Spanish |

---

## 5. Agent Assist Lambda

The agent assist is a custom Lambda (`agent-copilot-dev-agent-assist`) that receives each caller transcript segment and returns real-time suggestions to the agent UI.

### Lambda environment variables

| Variable | Value |
|----------|-------|
| `MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` (fast inference) |
| `DYNAMODB_TABLE_NAME` | `agent-copilot-dev-AISTACK-…-EventSourcingTable-…` |
| `TABLA_PLANES` | `agent-copilot-dev-telco-planes` |
| `TABLA_CLIENTES` | `agent-copilot-dev-telco-clientes` |
| `TABLA_OFERTAS` | `agent-copilot-dev-telco-ofertas` |
| `KNOWLEDGE_BASE_ID` | `AIYIMOJHD9` |

### DynamoDB tables (custom)

Three TelcoStrata-specific tables provide structured lookups:

| Table | Content |
|-------|---------|
| `telco-planes` | Mobile and home internet plan catalog with prices, features, GB |
| `telco-clientes` | Demo client profiles for testing |
| `telco-ofertas` | Retention offers mapped by tier (RET-A through RET-D) |

### Bedrock Knowledge Base (`AIYIMOJHD9`)

Semantic RAG over two document sets in `strata-deploy-to-dev/kb-files/`:

**`kb_planes_descripcion.json`** — full plan catalog:
- Mobile: Basic (5GB), Plus (15GB+social), Pro (30GB+5G+roaming), Unlimited (5G+hotspot+40+ countries), Familiar 3-line, Familiar 5-line
- Home internet: 50/100/300 Mbps, Giga (1 Gbps)
- Bundle: 15% discount mobile+home

**`kb_ofertas_retencion_scripts.json`** — retention playbook (4 tiers):
| Offer | Trigger | Benefit |
|-------|---------|---------|
| RET-A | Customer <6 months | 20% off for 3 months |
| RET-B | RET-A rejected or >12 months | Free upgrade for 6 months |
| RET-C | High-value customer (>24 mo or >$500/mo) | 30% off + upgrade for 3 months |
| RET-D | Economic hardship / temporary situation | Service pause for 3 months at no charge |

### AI model for summaries

| Parameter | Value |
|-----------|-------|
| `EndOfCallTranscriptSummary` | `BEDROCK` |
| `SummaryBedrockModelId` | `us.amazon.nova-lite-v1:0` |
| `AgentAssistLLMBedrockModelId` | `us.amazon.nova-lite-v1:0` |

---

## 6. Real-Time Call Categories

Call categories flag significant moments in the conversation (e.g., customer wants to cancel). AWS Transcribe Call Analytics provided these natively via `CategoryEvent` objects. With Deepgram, they are replaced by a regex engine in the `call_event_processor` Lambda.

### How it works

After each finalized transcript segment, the Lambda checks the text against compiled regex patterns stored in SSM Parameter Store. A match emits a `CATEGORY_MATCH` event to AppSync — the same event the UI uses to display category pills.

### Current patterns (dev)

| Category | Trigger keywords (Spanish) |
|----------|---------------------------|
| **Retention Risk** | cancelar, baja, darme de baja, terminar el servicio, no quiero seguir, dejar de ser cliente |
| **Complaint** | queja, reclamo, molest, mal servicio, pésimo, terrible, estoy harto |
| **Plan Inquiry** | plan, precio, costo, tarifa, cuánto cuesta, oferta, promoción, descuento |
| **Technical Issue** | no funciona, falla, sin señal, sin internet, corte, muy lento, velocidad baja |

### Updating patterns without redeploying

Patterns refresh every 60 seconds from SSM. Use the helper script:

```bash
# Show current patterns
python strata-deploy-to-dev/update-categories.py --profile dev

# Add or update a pattern
python strata-deploy-to-dev/update-categories.py --profile dev \
  --add "Upgrade Interest" "(?i)\b(quiero mejorar|plan más alto|subir de plan)\b"

# Remove a pattern
python strata-deploy-to-dev/update-categories.py --profile dev --remove "Retention Risk"
```

### Files changed

| File | Change |
|------|--------|
| `lca-main.yaml` | Added `TranscriptCategoryPatterns` CFN parameter |
| `lca-ai-stack/source/lambda_functions/call_event_processor/lambda_function.py` | Compiles regex patterns at startup + 60s TTL refresh |
| `lca-ai-stack/source/lambda_functions/call_event_processor/event_processor/call_event_processor.py` | Applies patterns on each non-partial transcript segment |
| `strata-deploy-to-dev/update-categories.py` | Helper script to update patterns live |

---

## 7. UI Branding

The React UI uses TelcoStrata branding while keeping the underlying Cloudscape component structure.

| Element | Customization |
|---------|--------------|
| App name | **Agent Copilot** |
| Top navigation logo | `strata-logo-white.png` (white variant on colored nav bar) |
| Login / password-reset screen | `strata-logo.png` (dark variant) |
| Connect CCP URL | `https://lca-demo-strata.my.connect.aws/connect/ccp-v2` |

### Logo files

- `lca-ai-stack/source/ui/public/strata-logo.png` (dark, 24 KB)
- `lca-ai-stack/source/ui/public/strata-logo-white.png` (white, 51 KB)

### Files changed

| File | Change |
|------|--------|
| `lca-ai-stack/source/ui/src/components/call-analytics-top-navigation/CallAnalyticsTopNavigation.jsx` | Replaced AWS logo with TelcoStrata white logo + "Copilot" text |
| `lca-ai-stack/source/ui/src/routes/UnauthRoutes.jsx` | TelcoStrata logo + "Copilot" text on login screens |
| `lca-ai-stack/source/ui/src/layouts/ConnectLayout.jsx` | Hardcoded Connect CCP URL for TelcoStrata |

---

## 8. Telephony & Audio

| Parameter | Value |
|-----------|-------|
| `CallAudioSource` | Amazon Connect Kinesis Video Streams |
| `CallAudioProcessor` | Amazon Chime SDK Call Analytics |
| `CustomVoiceConnectorId` | `bpma7dkadecjeiien6ohjn` |
| `SiprecAllowedCidrList` | `190.210.32.166/32` (dev) |
| `WebSocketAudioInput` | Enabled (browser-based demo calls) |
| `ChimeVoiceToneAnalysis` | Enabled |
| `IsPartialTranscriptEnabled` | true |
| `IsSentimentAnalysisEnabled` | true |
| `SentimentNegativeScoreThreshold` | 0.9 |
| `SentimentPositiveScoreThreshold` | 0.4 |

---

## 9. Data Retention

| Parameter | Value |
|-----------|-------|
| `DynamoDbExpirationInDays` | 7 |
| `AudioRecordingExpirationInDays` | 7 |
| `AudioFilePrefix` | `lca-audio-recordings/` |
| `CallAnalyticsPrefix` | `lca-call-analytics/` |

---

## 10. CI/CD Pipeline

Automated deployment to the dev environment on every push to `develop`.

**File:** `.github/workflows/deploy-dev.yml`

### Steps

1. **Checkout** — pull latest code
2. **AWS credentials** — OIDC role (no long-lived keys): `secrets.AWS_ROLE_ARN`
3. **Read VERSION** — from `VERSION` file
4. **Upload modified sub-stacks** — `lca-vpc-stack`, `lca-chimevc-stack`, `lca-connect-kvs-stack`, `lca-websocket-transcriber-stack` (packaged and uploaded to `agent-copilot-dev-cfn-templates` S3 bucket)
5. **Process `lca-main.yaml`** — replaces tokens (`<REGION_TOKEN>`, etc.), redirects sub-stack TemplateURLs from AWS public bucket to our S3 bucket
6. **Validate and deploy CloudFormation** — `aws cloudformation deploy` with parameters from `lca-stack-parameters-dev.json`; masked (`****`) values use previous CloudFormation value, with `DEEPGRAM_API_KEY` injected directly from GitHub Secret
7. **Build and push Docker image** — ECS Fargate transcriber image built locally in CI (because CodeBuild downloads the original AWS ZIP, not our custom code), pushed to ECR tag `0.9.7`, then `aws ecs update-service --force-new-deployment`
8. **Failure diagnostics** — on failure, prints the 30 most recent CloudFormation stack events
9. **Success summary** — prints stack name, branch, commit, region

### GitHub Secrets required

| Secret | Purpose |
|--------|---------|
| `AWS_ROLE_ARN` | OIDC role ARN for dev account |
| `DEEPGRAM_API_KEY` | Injected into CloudFormation as `DeepgramApiKey` parameter |

### AWS resources (static, not created by CI)

| Resource | Value |
|----------|-------|
| CFN artifacts bucket | `agent-copilot-dev-cfn-templates` |
| ECR repository | `637423400532.dkr.ecr.us-east-1.amazonaws.com/…transcriberecrrepository-wq0jboagdpf2` |
| ECS cluster | `agent-copilot-dev-WEBSOCKETTRANSCRIBERSTACK-…-TranscribingCluster-…` |
| ECS service | `agent-copilot-dev-WEBSOCKETTRANSCRIBERSTACK-…-TranscriberWebsocketFargateService-…` |

---

## 11. APN Tagging

All CloudFormation resources are tagged with `aws-apn-id` as required by the AWS Partner Network.

**Files:** `lca-chimevc-stack/template.yaml`, `lca-vpc-stack/template.yaml`, and root-stack Lambda/LogGroup resources.

**Audit tool:** `strata-deploy-to-dev/verify_aws_apn_tagging.ipynb`

---

## 12. Admin

| Parameter | Value |
|-----------|-------|
| `AdminEmail` | `valentina.gomez@strata-analytics.us` |
| `AllowedSignUpEmailDomain` | (open — any email can sign up) |
| `CloudFrontPriceClass` | `PriceClass_100` (US/EU only) |
| `CloudFrontAllowedGeos` | (no geo restriction) |

---

## Rollback

To revert to AWS Transcribe Call Analytics, change two parameters in `lca-stack-parameters-dev.json` and push:

```json
{ "ParameterKey": "TranscribeApiMode",    "ParameterValue": "analytics" },
{ "ParameterKey": "TranscriberEngine",    "ParameterValue": "standard"  }
```

No code changes required. The `startDeepgram()` function remains dormant until `TranscribeApiMode=deepgram` is set again.
