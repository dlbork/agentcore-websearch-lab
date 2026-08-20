"""Provisions the AgentCore Gateway + Web Search connector target.

Two separate IAM sides, per AWS's docs:
  - Outbound: the Gateway's own service role needs bedrock-agentcore:InvokeWebSearch
    on the managed web-search tool, and bedrock-agentcore:InvokeGateway on the
    Gateway itself. Granted via the GATEWAY_IAM_ROLE credential provider.
  - Inbound: whoever calls the Gateway (this app, via aws_iam_streamablehttp_client)
    needs bedrock-agentcore:InvokeGateway on the Gateway ARN. With
    authorizerType=AWS_IAM this is a plain SigV4-signed call, no Cognito/OAuth.

The service role's trust policy references the Gateway's own ARN, which
doesn't exist until create_gateway() returns — so the trust policy is
created loose (no ArnLike condition) and tightened in a second pass once the
Gateway ARN is known.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import boto3

REGION = "us-east-1"
GATEWAY_NAME = "agentcore-websearch-lab"
TARGET_NAME = "web-search-tool"
ROLE_NAME = "agentcore-websearch-lab-gateway-role"
WEB_SEARCH_TOOL_ARN = "arn:aws:bedrock-agentcore:us-east-1:aws:tool/web-search.v1"

TRUST_POLICY_TEMPLATE = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "GatewayAssumeRolePolicy",
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def _account_id(sts_client) -> str:
    return sts_client.get_caller_identity()["Account"]


def _clients():
    session = boto3.Session(region_name=REGION)
    return (
        session.client("bedrock-agentcore-control"),
        session.client("iam"),
        session.client("sts"),
    )


def ensure_service_role(iam_client, account_id: str) -> str:
    """Create (or reuse) the Gateway's service role with a loose trust policy.

    Returns the role ARN. The trust policy is tightened to the specific
    Gateway ARN in tighten_trust_policy() once the Gateway exists.
    """
    try:
        role = iam_client.get_role(RoleName=ROLE_NAME)["Role"]
        print(f"service role exists: {role['Arn']}")
        return role["Arn"]
    except iam_client.exceptions.NoSuchEntityException:
        pass

    role = iam_client.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY_TEMPLATE),
        Description="Outbound service role for agentcore-websearch-lab Gateway",
    )["Role"]
    print(f"created service role: {role['Arn']}")

    iam_client.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="invoke-web-search",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "InvokeWebSearchTool",
                        "Effect": "Allow",
                        "Action": "bedrock-agentcore:InvokeWebSearch",
                        "Resource": WEB_SEARCH_TOOL_ARN,
                    }
                ],
            }
        ),
    )
    print("attached outbound policy: bedrock-agentcore:InvokeWebSearch")

    # IAM roles are eventually consistent; give it a moment before the
    # Gateway tries to assume it.
    time.sleep(8)
    return role["Arn"]


def tighten_trust_policy(iam_client, account_id: str, gateway_arn: str) -> None:
    """Second pass: scope the trust policy to this specific Gateway's ARN."""
    policy = dict(TRUST_POLICY_TEMPLATE)
    policy["Statement"] = [
        {
            **TRUST_POLICY_TEMPLATE["Statement"][0],
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
                "ArnLike": {"aws:SourceArn": gateway_arn},
            },
        }
    ]
    iam_client.update_assume_role_policy(
        RoleName=ROLE_NAME, PolicyDocument=json.dumps(policy)
    )
    print(f"tightened trust policy to gateway ARN: {gateway_arn}")


def _wait_for_gateway(control_client, gateway_id: str, timeout_s: int = 120) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        gw = control_client.get_gateway(gatewayIdentifier=gateway_id)
        if gw["status"] == "READY":
            return gw
        if gw["status"] == "FAILED":
            raise RuntimeError(f"Gateway creation failed: {gw.get('statusReasons')}")
        time.sleep(5)
    raise TimeoutError(f"Gateway {gateway_id} did not become READY within {timeout_s}s")


def _wait_for_target(control_client, gateway_id: str, target_id: str, timeout_s: int = 120) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        target = control_client.get_gateway_target(
            gatewayIdentifier=gateway_id, targetId=target_id
        )
        if target["status"] == "READY":
            return target
        if target["status"] in ("FAILED", "SYNCHRONIZE_UNSUCCESSFUL", "UPDATE_UNSUCCESSFUL"):
            raise RuntimeError(f"Gateway target failed: {target.get('statusReasons')}")
        time.sleep(5)
    raise TimeoutError(f"Target {target_id} did not become READY within {timeout_s}s")


def _find_existing_gateway(control_client) -> dict | None:
    for gw in control_client.list_gateways().get("items", []):
        if gw["name"] == GATEWAY_NAME:
            return control_client.get_gateway(gatewayIdentifier=gw["gatewayId"])
    return None


def setup() -> dict:
    control, iam, sts = _clients()
    account_id = _account_id(sts)

    role_arn = ensure_service_role(iam, account_id)

    existing = _find_existing_gateway(control)
    if existing:
        print(f"gateway already exists: {existing['gatewayArn']} ({existing['status']})")
        gateway = existing if existing["status"] == "READY" else _wait_for_gateway(
            control, existing["gatewayId"]
        )
    else:
        created = control.create_gateway(
            name=GATEWAY_NAME,
            roleArn=role_arn,
            protocolType="MCP",
            authorizerType="AWS_IAM",
        )
        print(f"creating gateway: {created['gatewayId']} ... waiting for READY")
        gateway = _wait_for_gateway(control, created["gatewayId"])

    tighten_trust_policy(iam, account_id, gateway["gatewayArn"])

    targets = control.list_gateway_targets(gatewayIdentifier=gateway["gatewayId"]).get(
        "items", []
    )
    existing_target = next((t for t in targets if t["name"] == TARGET_NAME), None)
    if existing_target:
        print(f"gateway target already exists: {existing_target['targetId']}")
        target = existing_target if existing_target["status"] == "READY" else _wait_for_target(
            control, gateway["gatewayId"], existing_target["targetId"]
        )
    else:
        created_target = control.create_gateway_target(
            gatewayIdentifier=gateway["gatewayId"],
            name=TARGET_NAME,
            targetConfiguration={
                "mcp": {
                    "connector": {
                        "source": {"connectorId": "web-search"},
                        "configurations": [{"name": "WebSearch", "parameterValues": {}}],
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        print(f"creating gateway target: {created_target['targetId']} ... waiting for READY")
        target = _wait_for_target(control, gateway["gatewayId"], created_target["targetId"])

    result = {
        "gateway_id": gateway["gatewayId"],
        "gateway_arn": gateway["gatewayArn"],
        "gateway_url": gateway["gatewayUrl"],
        "role_arn": role_arn,
        "target_id": target["targetId"],
        "target_status": target["status"],
    }
    print(json.dumps(result, indent=2))
    return result


def teardown() -> None:
    control, iam, _sts = _clients()

    existing = _find_existing_gateway(control)
    if existing:
        gateway_id = existing["gatewayId"]
        for t in control.list_gateway_targets(gatewayIdentifier=gateway_id).get("items", []):
            print(f"deleting gateway target: {t['targetId']}")
            control.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=t["targetId"])
        print(f"deleting gateway: {gateway_id}")
        control.delete_gateway(gatewayIdentifier=gateway_id)
    else:
        print("no matching gateway found, nothing to delete")

    try:
        for policy in iam.list_role_policies(RoleName=ROLE_NAME).get("PolicyNames", []):
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=policy)
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"deleted service role: {ROLE_NAME}")
    except iam.exceptions.NoSuchEntityException:
        print("service role already gone")


def status() -> dict | None:
    control, _iam, _sts = _clients()
    gateway = _find_existing_gateway(control)
    if not gateway:
        print("no gateway provisioned")
        return None
    targets = control.list_gateway_targets(gatewayIdentifier=gateway["gatewayId"]).get(
        "items", []
    )
    result = {
        "gateway_arn": gateway["gatewayArn"],
        "gateway_url": gateway.get("gatewayUrl"),
        "gateway_status": gateway["status"],
        "targets": [{"id": t["targetId"], "status": t["status"]} for t in targets],
    }
    print(json.dumps(result, indent=2))
    return result


def cli() -> None:
    parser = argparse.ArgumentParser(prog="agentcore-websearch-provision")
    parser.add_argument("action", choices=["setup", "teardown", "status"])
    args = parser.parse_args()

    if args.action == "setup":
        setup()
    elif args.action == "teardown":
        teardown()
    elif args.action == "status":
        status()


if __name__ == "__main__":
    cli()
    sys.exit(0)
