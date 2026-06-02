#!/usr/bin/env python3
"""
Multi-turn identity + conversation flow test — DEMO account (connect profile).

Seeds EventSourcingTable progressively — each turn sees all prior turns in context.

Identity states tested:
  4A — Veronica: phone+name → CONFIRMADO directly (no document step)
  4B — Ana: MISMATCH_PENDIENTE_DOCUMENTO → doc given → CONFIRMADO → conversation
  4C — Pedro: CLIENTE_DESCONOCIDO → ESCALACIÓN immediately
  5A — Ana: MISMATCH → wrong doc → DOCUMENTO_NO_COINCIDE → correct doc → CONFIRMADO

Usage:
  cd /Users/valentinagomez/Desktop/amazon-transcribe-live-call-analytics
  python3 strata-deploy-to-demo/test_multiturn_demo.py
"""

import boto3
import json
import time
from boto3.dynamodb.conditions import Key

REGION        = "us-east-1"
PROFILE       = "connect"
FUNCTION_NAME = "lca-poc-agent-assist"
TABLE_NAME    = "lca-poc-copilot-AISTACK-1Y2O3J3MDOH6R-EventSourcingTable-3KHT1JCM1TUW"

session  = boto3.Session(profile_name=PROFILE, region_name=REGION)
dyn      = session.resource("dynamodb")
lmb      = session.client("lambda")
table    = dyn.Table(TABLE_NAME)


# ── helpers ──────────────────────────────────────────────────────────────────

def cleanup(pk):
    resp = table.query(KeyConditionExpression=Key('PK').eq(pk))
    for item in resp.get('Items', []):
        table.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})


def seed(pk, sk, channel, segment_id, transcript):
    table.put_item(Item={
        'PK': pk, 'SK': sk,
        'Channel': channel,
        'SegmentId': segment_id,
        'Transcript': transcript,
    })


def invoke(pk, call_id, phone, text, segment_id):
    payload = {
        "CustomerPhoneNumber": phone,
        "text": text,
        "call_id": call_id,
        "dynamodb_pk": pk,
        "segmentId": segment_id,
        "isPartial": False,
    }
    resp = lmb.invoke(
        FunctionName=FUNCTION_NAME,
        Payload=json.dumps(payload).encode(),
    )
    return json.loads(resp["Payload"].read()).get("message", "")


def check(msg, must_have=None, must_not_have=None):
    ml = msg.lower()
    ok = True
    fails = []
    if must_have:
        for s in must_have:
            if s.lower() not in ml:
                ok = False
                fails.append(f"missing: '{s}'")
    if must_not_have:
        for s in must_not_have:
            if s.lower() in ml:
                ok = False
                fails.append(f"unexpected: '{s}'")
    return ok, fails


def run_scenario(title, phone, call_id, turns):
    """
    turns: list of dicts:
      {
        "customer": str,          # what the customer says
        "must_have": [str],       # substrings the response MUST contain
        "must_not_have": [str],   # substrings the response must NOT contain
        "label": str,             # short description of what to verify
      }
    """
    pk = f"c#{call_id}"
    print(f"\n{'═'*65}")
    print(f"SCENARIO: {title}")
    print(f"Phone: {phone}  |  Call ID: {call_id}")
    print(f"{'═'*65}")

    context_sk_counter = 0
    all_passed = True

    try:
        for i, turn in enumerate(turns, 1):
            seg_id = f"seg-turn-{i}"
            response = invoke(pk, call_id, phone, turn["customer"], seg_id)

            ok, fails = check(
                response,
                must_have=turn.get("must_have"),
                must_not_have=turn.get("must_not_have"),
            )
            status = "✅" if ok else "❌"
            if not ok:
                all_passed = False

            print(f"\n  Turn {i} — {turn.get('label','')}")
            print(f"  Customer : {turn['customer']}")
            print(f"  Response : {response or '(empty — ESPERAR)'}")
            print(f"  Check    : {status}{' — ' + ', '.join(fails) if fails else ''}")

            # Seed customer turn into context for next iterations
            context_sk_counter += 1
            seed(pk, f"{context_sk_counter:03d}-caller", "CALLER",
                 f"seg-ctx-caller-{i}", turn["customer"])

            # Seed copilot response into context (if non-empty)
            if response:
                context_sk_counter += 1
                seed(pk, f"{context_sk_counter:03d}-copilot", "AGENT_ASSISTANT",
                     f"seg-ctx-copilot-{i}", response)

            time.sleep(0.2)

        result = "✅ ALL PASS" if all_passed else "❌ SOME FAILED"
        print(f"\n  Scenario result: {result}")

    finally:
        cleanup(pk)
        print(f"  Cleaned up context for {pk}")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4A — Veronica: phone+name → CONFIRMADO (no document step)
# Phone matches Veronica Rivera (MOV-PLUS). Name matches → CONFIRMADO directly.
# ─────────────────────────────────────────────────────────────────────────────
run_scenario(
    title="4A — Veronica: phone+name CONFIRMADO, no document needed",
    phone="525533154775",
    call_id="demo-4a-5turns",
    turns=[
        {
            "label": "greeting without name → must ask for name",
            "customer": "Buenas tardes, quería consultar sobre mi plan.",
            "must_have": ["nombre"],
            "must_not_have": ["veronica", "mov-plus", "$299", "documento"],
        },
        {
            "label": "gives name → CONFIRMADO via phone+name, no doc step",
            "customer": "Soy Veronica Rivera.",
            "must_have": [],
            "must_not_have": ["documento", "verificar"],
        },
        {
            "label": "asks about plan options → agent uses Veronica's profile",
            "customer": "¿Qué opciones de plan tienen para mí?",
            "must_have": [],
            "must_not_have": ["documento", "verificar"],
        },
        {
            "label": "asks about travel roaming → correct upsell to MOV-PRO",
            "customer": "Viajo mucho a Estados Unidos por trabajo, ¿necesito algo especial?",
            "must_have": ["roaming", "mov-pro"],
            "must_not_have": ["documento"],
        },
        {
            "label": "accepts plan → CIERRE with plan name + price",
            "customer": "Me parece bien el plan Pro, lo quiero activar.",
            "must_have": ["cierre", "mov-pro", "$449"],
            "must_not_have": ["documento"],
        },
        {
            "label": "monosyllable confirm → final activation, no re-ask",
            "customer": "Sí.",
            "must_have": ["gracias"],
            "must_not_have": ["confirmamos", "activamos", "¿confirmamos", "¿activamos"],
        },
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4B — Ana: MISMATCH resolved via document, full conversation
# Phone = Veronica (MOV-PLUS), but Ana Martínez calls (MOV-BASIC, 5GB limit, 9GB avg)
# ─────────────────────────────────────────────────────────────────────────────
run_scenario(
    title="4B — Ana: MISMATCH → document validation → full conversation",
    phone="525533154775",
    call_id="demo-4b-5turns",
    turns=[
        {
            "label": "Ana's name on Veronica's phone → MISMATCH → must ask for document",
            "customer": "Soy Ana Martínez, llamo para ver mis opciones de plan.",
            "must_have": ["documento"],
            "must_not_have": ["mov-plus", "12gb", "veronica", "es usted"],
        },
        {
            "label": "gives correct document → CONFIRMADO with Ana's profile",
            "customer": "Mi número de documento es 55667788.",
            "must_have": ["ana"],
            "must_not_have": ["veronica", "documento", "verificar"],
        },
        {
            "label": "asks for recommendation → MOV-PLUS upsell with Ana's GAP",
            "customer": "¿Qué plan me recomendarían?",
            "must_have": ["ana"],
            "must_not_have": ["veronica", "30gb", "mov-pro", "documento"],
        },
        {
            "label": "price objection → MANEJO_OBJECION with 20% discount",
            "customer": "Está caro, no sé si me conviene pagar $100 más.",
            "must_have": ["239"],
            "must_not_have": ["veronica", "documento"],
        },
        {
            "label": "accepts discounted offer → CIERRE with details",
            "customer": "Bueno, con ese descuento me interesa. Lo activo.",
            "must_have": ["cierre", "239"],
            "must_not_have": ["veronica", "documento"],
        },
        {
            "label": "monosyllable confirm → final activation, no re-ask",
            "customer": "Sí.",
            "must_have": ["gracias"],
            "must_not_have": ["confirmamos", "activamos", "¿confirmamos", "¿activamos"],
        },
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4C — Pedro: CLIENTE_DESCONOCIDO → ESCALACIÓN immediately
# Phone = Veronica, Pedro not in DB → no qualification, escalate right away
# ─────────────────────────────────────────────────────────────────────────────
run_scenario(
    title="4C — Pedro: unknown client → immediate ESCALACIÓN",
    phone="525533154775",
    call_id="demo-4c-5turns",
    turns=[
        {
            "label": "unknown name → must escalate immediately, no qualification attempts",
            "customer": "Me llamo Pedro López, llamo para consultar.",
            "must_have": ["pedro", "especialista"],
            "must_not_have": ["mov-plus", "veronica", "12gb", "¿tiene actualmente"],
        },
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5A — Ana: MISMATCH → wrong doc → DOCUMENTO_NO_COINCIDE → correct doc → CONFIRMADO
# Phone = Veronica. Ana calls, gives wrong doc first, then correct doc.
# ─────────────────────────────────────────────────────────────────────────────
run_scenario(
    title="5A — Ana: MISMATCH with wrong doc then correct doc (DOCUMENTO_NO_COINCIDE flow)",
    phone="525533154775",
    call_id="demo-5a-docval",
    turns=[
        {
            "label": "Ana's name → MISMATCH → must ask for document",
            "customer": "Soy Ana Martínez, llamo para consultar sobre mi plan.",
            "must_have": ["documento"],
            "must_not_have": ["mov-plus", "$299", "veronica", "es usted"],
        },
        {
            "label": "gives wrong document → DOCUMENTO_NO_COINCIDE → must re-ask",
            "customer": "Mi número de documento es 12345678.",
            "must_have": ["documento"],
            "must_not_have": ["mov-basic", "veronica", "cierre"],
        },
        {
            "label": "gives correct document → CONFIRMADO → proceed with Ana's profile",
            "customer": "Ah, disculpe, es el 55667788.",
            "must_have": ["ana"],
            "must_not_have": ["documento", "verificar", "veronica"],
        },
        {
            "label": "asks about plan → agent uses Ana's profile, no more doc ask",
            "customer": "¿Qué opciones de plan tienen para mí?",
            "must_have": ["ana"],
            "must_not_have": ["documento", "veronica"],
        },
        {
            "label": "accepts recommendation → CIERRE",
            "customer": "Me parece bien el plan Plus, lo quiero.",
            "must_have": ["cierre"],
            "must_not_have": ["documento", "veronica"],
        },
    ],
)

print(f"\n{'═'*65}")
print("All scenarios complete.")
print(f"{'═'*65}\n")
