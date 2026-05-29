#!/usr/bin/env python3
"""
Update TranscriptCategoryPatterns in SSM Parameter Store without redeploying.

Changes take effect within ~60 seconds (Lambda TTL cache).

Usage:
  python strata-deploy-to-dev/update-categories.py --profile dev          # show current patterns
  python strata-deploy-to-dev/update-categories.py --profile dev --set    # open editor to set patterns
  python strata-deploy-to-dev/update-categories.py --profile dev --add "Retention Risk" "(?i)\\b(cancelar|baja)\\b"
  python strata-deploy-to-dev/update-categories.py --profile dev --remove "Retention Risk"
  python strata-deploy-to-dev/update-categories.py --profile dev --clear  # remove all patterns

The SSM parameter name is read from the deployed CloudFormation stack.
"""
import argparse
import boto3
import json
import re
import sys

STACK_NAME = "agent-copilot-dev"
REGION = "us-east-1"


def get_ssm_param_name(profile: str) -> str:
    session = boto3.Session(profile_name=profile, region_name=REGION)
    cfn = session.client("cloudformation")
    response = cfn.describe_stack_resources(
        StackName=STACK_NAME,
        LogicalResourceId="LCASettingsParameter",
    )
    # LCASettingsParameter is in the AI sub-stack; walk exports if not found directly
    resources = response.get("StackResourceDetail", {})
    physical_id = resources.get("PhysicalResourceId", "")
    if not physical_id:
        # Try listing all stack resources (nested stacks)
        paginator = cfn.get_paginator("list_stack_resources")
        for page in paginator.paginate(StackName=STACK_NAME):
            for r in page["StackResourceSummaries"]:
                if r["LogicalResourceId"] == "LCASettingsParameter":
                    return r["PhysicalResourceId"]
        # Fallback: search nested AI stack
        for page in paginator.paginate(StackName=STACK_NAME):
            for r in page["StackResourceSummaries"]:
                if "AISTACK" in r.get("PhysicalResourceId", "") or "AISTACK" in r.get("LogicalResourceId", ""):
                    nested = r["PhysicalResourceId"]
                    for page2 in cfn.get_paginator("list_stack_resources").paginate(StackName=nested):
                        for r2 in page2["StackResourceSummaries"]:
                            if r2["LogicalResourceId"] == "LCASettingsParameter":
                                return r2["PhysicalResourceId"]
        print("ERROR: Could not locate LCASettingsParameter in stack. Set SSM_PARAM_NAME env var.")
        sys.exit(1)
    return physical_id


def load_settings(ssm, param_name: str) -> dict:
    resp = ssm.get_parameter(Name=param_name)
    return json.loads(resp["Parameter"]["Value"])


def save_settings(ssm, param_name: str, settings: dict) -> None:
    ssm.put_parameter(
        Name=param_name,
        Value=json.dumps(settings),
        Type="String",
        Overwrite=True,
    )


def get_patterns(settings: dict) -> list:
    raw = settings.get("TranscriptCategoryPatterns", "[]")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def set_patterns(settings: dict, patterns: list) -> None:
    settings["TranscriptCategoryPatterns"] = json.dumps(patterns, ensure_ascii=False)


def validate_pattern(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error as e:
        print(f"Invalid regex: {e}")
        return False


def print_patterns(patterns: list) -> None:
    if not patterns:
        print("  (no patterns configured)")
        return
    for i, p in enumerate(patterns, 1):
        print(f"  {i}. [{p['name']}]  →  {p['pattern']}")


def main():
    parser = argparse.ArgumentParser(description="Manage LCA transcript category patterns in SSM")
    parser.add_argument("--profile", default="dev", help="AWS profile (default: dev)")
    parser.add_argument("--param", default=None, help="SSM parameter name (auto-detected from CFN if not set)")
    parser.add_argument("--add", nargs=2, metavar=("NAME", "PATTERN"), help="Add or update a category pattern")
    parser.add_argument("--remove", metavar="NAME", help="Remove a category pattern by name")
    parser.add_argument("--clear", action="store_true", help="Remove all patterns")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    ssm = session.client("ssm")

    if args.param:
        param_name = args.param
    else:
        print(f"Looking up SSM parameter from CloudFormation stack '{STACK_NAME}'...")
        try:
            param_name = get_ssm_param_name(args.profile)
        except Exception as e:
            print(f"Auto-detect failed ({e}). Use --param to specify the SSM parameter name directly.")
            sys.exit(1)

    print(f"SSM parameter: {param_name}\n")

    settings = load_settings(ssm, param_name)
    patterns = get_patterns(settings)

    if args.clear:
        patterns = []
        set_patterns(settings, patterns)
        save_settings(ssm, param_name, settings)
        print("All patterns cleared. Changes apply within ~60s.")
        return

    if args.add:
        name, pattern = args.add
        if not validate_pattern(pattern):
            sys.exit(1)
        # Update existing or append
        updated = False
        for p in patterns:
            if p["name"] == name:
                p["pattern"] = pattern
                updated = True
                break
        if not updated:
            patterns.append({"name": name, "pattern": pattern})
        set_patterns(settings, patterns)
        save_settings(ssm, param_name, settings)
        action = "Updated" if updated else "Added"
        print(f"{action} pattern '{name}'. Changes apply within ~60s.\n")
        print("Current patterns:")
        print_patterns(patterns)
        return

    if args.remove:
        before = len(patterns)
        patterns = [p for p in patterns if p["name"] != args.remove]
        if len(patterns) == before:
            print(f"Pattern '{args.remove}' not found.")
            sys.exit(1)
        set_patterns(settings, patterns)
        save_settings(ssm, param_name, settings)
        print(f"Removed pattern '{args.remove}'. Changes apply within ~60s.\n")
        print("Current patterns:")
        print_patterns(patterns)
        return

    # Default: show current patterns
    print("Current TranscriptCategoryPatterns:")
    print_patterns(patterns)


if __name__ == "__main__":
    main()
