#!/usr/bin/env python3
"""
Agrega el tag aws-apn-id a todos los recursos de un stack CloudFormation ya deployado.

Estrategia:
  1. Recorre recursivamente todos los nested stacks via CloudFormation API
  2. Por cada stack, busca sus recursos usando el tag automático
     aws:cloudformation:stack-name que CFn agrega a todos los recursos
  3. Los tagea en lotes usando Resource Groups Tagging API (20 ARNs por llamada)

Uso:
  python tag_apn_resources.py --stack-name <NOMBRE_STACK> [opciones]

Ejemplos:
  # Ver qué recursos se van a taguear (sin modificar nada)
  python tag_apn_resources.py --stack-name lca-poc-dev --dry-run

  # Taguear en us-east-1 con el profile default
  python tag_apn_resources.py --stack-name lca-poc-dev

  # Taguear con un profile específico
  python tag_apn_resources.py --stack-name lca-poc-dev --profile strata-dev --region us-east-1

Requisitos:
  pip install boto3
  Permisos IAM necesarios:
    - cloudformation:ListStackResources
    - tag:GetResources
    - tag:TagResources
"""

import boto3
import argparse
import sys
from typing import Set, List

# ─── Configuración del tag ────────────────────────────────────────────────────
TAG_KEY   = "aws-apn-id"
TAG_VALUE = "pc:4da0ebcd14f35cd0p3n9zpm5l"
# ─────────────────────────────────────────────────────────────────────────────


def get_all_stack_names(cfn_client, stack_id: str, collected: Set[str] = None, depth: int = 0) -> Set[str]:
    """
    Recorre recursivamente el árbol de nested stacks y retorna
    todos los nombres cortos de stack (los que aparecen en el tag
    aws:cloudformation:stack-name de los recursos).
    """
    if collected is None:
        collected = set()

    # El nombre corto es lo que está entre 'stack/' y el siguiente '/'
    # ARN format: arn:aws:cloudformation:region:account:stack/STACK-NAME/guid
    if stack_id.startswith("arn:"):
        short_name = stack_id.split(":stack/")[1].split("/")[0]
    else:
        short_name = stack_id

    if short_name in collected:
        return collected  # evita ciclos

    collected.add(short_name)
    indent = "  " * depth
    print(f"{indent}📦 {short_name}")

    try:
        paginator = cfn_client.get_paginator("list_stack_resources")
        for page in paginator.paginate(StackName=stack_id):
            for resource in page["StackResourceSummaries"]:
                if resource["ResourceType"] == "AWS::CloudFormation::Stack":
                    status = resource.get("ResourceStatus", "")
                    if "DELETE" not in status and "physical_resource_id" not in resource.get("PhysicalResourceId", ""):
                        nested_id = resource.get("PhysicalResourceId", "")
                        if nested_id:
                            get_all_stack_names(cfn_client, nested_id, collected, depth + 1)
    except Exception as e:
        print(f"{indent}  ⚠️  No se pudo listar recursos de '{short_name}': {e}")

    return collected


def get_resource_arns_for_stack(tagging_client, stack_name: str) -> List[str]:
    """
    Retorna todos los ARNs de recursos que tienen el tag
    aws:cloudformation:stack-name = stack_name.
    """
    arns = []
    try:
        paginator = tagging_client.get_paginator("get_resources")
        for page in paginator.paginate(
            TagFilters=[{"Key": "aws:cloudformation:stack-name", "Values": [stack_name]}],
            ResourcesPerPage=100,
        ):
            for resource in page["ResourceTagMappingList"]:
                arns.append(resource["ResourceARN"])
    except Exception as e:
        print(f"  ⚠️  Error obteniendo recursos de '{stack_name}': {e}")
    return arns


def already_tagged(resource: dict) -> bool:
    """Verifica si el recurso ya tiene el tag aws-apn-id."""
    for tag in resource.get("Tags", []):
        if tag["Key"] == TAG_KEY:
            return True
    return False


def get_resource_arns_excluding_already_tagged(tagging_client, stack_name: str) -> tuple[List[str], int]:
    """
    Retorna (arns_a_taguear, cantidad_ya_tagueados).
    """
    to_tag = []
    already_done = 0
    try:
        paginator = tagging_client.get_paginator("get_resources")
        for page in paginator.paginate(
            TagFilters=[{"Key": "aws:cloudformation:stack-name", "Values": [stack_name]}],
            ResourcesPerPage=100,
        ):
            for resource in page["ResourceTagMappingList"]:
                if already_tagged(resource):
                    already_done += 1
                else:
                    to_tag.append(resource["ResourceARN"])
    except Exception as e:
        print(f"  ⚠️  Error obteniendo recursos de '{stack_name}': {e}")
    return to_tag, already_done


def tag_in_batches(tagging_client, arns: List[str], dry_run: bool) -> dict:
    """
    Taguea los ARNs en lotes de 20 (límite de la API).
    Retorna dict con conteos de éxito y fallos.
    """
    results = {"success": 0, "failed": []}
    batch_size = 20

    for i in range(0, len(arns), batch_size):
        batch = arns[i : i + batch_size]

        if dry_run:
            results["success"] += len(batch)
            continue

        try:
            response = tagging_client.tag_resources(
                ResourceARNList=batch,
                Tags={TAG_KEY: TAG_VALUE},
            )
            failed_map = response.get("FailedResourcesMap", {})
            results["success"] += len(batch) - len(failed_map)
            for arn, error_info in failed_map.items():
                results["failed"].append(
                    {"arn": arn, "reason": error_info.get("ErrorMessage", str(error_info))}
                )
        except Exception as e:
            for arn in batch:
                results["failed"].append({"arn": arn, "reason": str(e)})

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Agrega el tag aws-apn-id a todos los recursos de un stack CloudFormation."
    )
    parser.add_argument(
        "--stack-name",
        required=True,
        help="Nombre del stack CloudFormation principal (ej: lca-poc-dev)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="Región AWS (default: us-east-1)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="AWS CLI profile (opcional, usa el default si no se especifica)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra cuántos recursos se tagearían sin modificar nada",
    )
    args = parser.parse_args()

    # ── Inicializar sesión ────────────────────────────────────────────────────
    session_kwargs = {"region_name": args.region}
    if args.profile:
        session_kwargs["profile_name"] = args.profile

    session     = boto3.Session(**session_kwargs)
    cfn         = session.client("cloudformation")
    tagging     = session.client("resourcegroupstaggingapi")

    # ── Header ────────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print(f"  Stack  : {args.stack_name}")
    print(f"  Tag    : {TAG_KEY} = {TAG_VALUE}")
    print(f"  Región : {args.region}")
    print(f"  Modo   : {'🔍 DRY RUN (sin cambios)' if args.dry_run else '🚀 LIVE (aplicando cambios)'}")
    print("=" * 65)

    # ── Paso 1: Descubrir todos los nested stacks ─────────────────────────────
    print("\n📋 Paso 1: Descubriendo nested stacks...\n")
    try:
        all_stacks = get_all_stack_names(cfn, args.stack_name)
    except Exception as e:
        print(f"\n❌ Error accediendo al stack '{args.stack_name}': {e}")
        print("   Verificá que el stack exista y que tengas permisos de CloudFormation.")
        sys.exit(1)

    print(f"\n   → {len(all_stacks)} stacks encontrados en total\n")

    # ── Paso 2: Recolectar ARNs de recursos ───────────────────────────────────
    print("📋 Paso 2: Recolectando recursos tagueables...\n")
    all_arns_to_tag  = []
    total_ya_tagueados = 0

    for stack_name in sorted(all_stacks):
        arns, ya_tagueados = get_resource_arns_excluding_already_tagged(tagging, stack_name)
        total_ya_tagueados += ya_tagueados
        all_arns_to_tag.extend(arns)
        status = f"{len(arns)} a taguear"
        if ya_tagueados:
            status += f", {ya_tagueados} ya tagueados"
        print(f"  {stack_name}: {status}")

    # Deduplicar (un recurso puede aparecer en múltiples stacks si se comparte)
    all_arns_to_tag = list(set(all_arns_to_tag))

    print(f"\n  → {len(all_arns_to_tag)} recursos a taguear")
    if total_ya_tagueados:
        print(f"  → {total_ya_tagueados} ya tienen el tag (se saltean)")

    if not all_arns_to_tag:
        print("\n✅ No hay recursos pendientes de taguear.")
        sys.exit(0)

    # ── Paso 3: Aplicar el tag ────────────────────────────────────────────────
    action = "Simulando tageo" if args.dry_run else f"Aplicando {TAG_KEY}={TAG_VALUE}"
    print(f"\n📋 Paso 3: {action}...\n")

    results = tag_in_batches(tagging, all_arns_to_tag, dry_run=args.dry_run)

    # ── Resumen ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  RESUMEN")
    print("=" * 65)
    if args.dry_run:
        print(f"  [DRY RUN] Se tagearían: {results['success']} recursos")
    else:
        print(f"  ✅ Tagueados exitosamente : {results['success']}")
        print(f"  ❌ Fallidos               : {len(results['failed'])}")

    if results["failed"]:
        print("\n  Recursos con error:")
        for item in results["failed"]:
            # Acortar el ARN para que sea legible
            arn_short = item["arn"].split(":")[-1][:60]
            print(f"    • ...{arn_short}")
            print(f"      Motivo: {item['reason']}")
        print(
            "\n  ⚠️  Los fallos suelen ser recursos que no soportan tagging via API"
            "\n     (ej: CloudWatch LogGroups, IAM inline policies, Custom Resources)."
            "\n     Esto es esperado y no afecta el funcionamiento del stack."
        )

    print("=" * 65 + "\n")

    if not args.dry_run and results["success"] > 0:
        print(f"✅ Listo. {results['success']} recursos tagueados con {TAG_KEY}={TAG_VALUE}\n")


if __name__ == "__main__":
    main()
