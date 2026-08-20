"""SigV4-signed MCP connection to the AgentCore Gateway.

With authorizerType=AWS_IAM on the Gateway, no Cognito/OAuth is needed —
aws_iam_streamablehttp_client signs each request with the caller's AWS
credentials directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

from agentcore_websearch.provisioning import REGION

AWS_SERVICE = "bedrock-agentcore"


@asynccontextmanager
async def gateway_session(gateway_url: str) -> AsyncIterator[ClientSession]:
    async with aws_iam_streamablehttp_client(
        endpoint=gateway_url,
        aws_service=AWS_SERVICE,
        aws_region=REGION,
    ) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session
