"""Read-only High Director MCP deployment preflight. No AWS changes.

Executed only on the temporary audit branch, inside GitHub Actions. Never
print credentials, source code or function environment variable values.
"""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import boto3
import requests

FUNCTION = "github-gpt-wrapper-GithubGptWrapper-SKhOCHfaqOtn"
OWNER = "warrengleeson"
REPO = "General_Director"
PATHS = (
    "auth0_bootstrap.py", "auth0_verification.py", "authenticated_mcp.py",
    "core.py", "lambda_dispatch.py", "live_wrapper_reader.py",
    "security.py", "shared_lambda.py", "token_verification.py",
)
MCP_RESOURCE = "https://z2yacqwhvykeh32xasdps5jwdm0nzmqh.lambda-url.us-east-2.on.aws/director/mcp"


def fetch_github_source(token: str, filename: str) -> bytes:
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/execution_plane/{filename}"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        params={"ref": "main"}, timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"MCP source read unavailable: {filename}, GitHub status {response.status_code}")
    record = response.json()
    if record.get("encoding") != "base64" or record.get("type") != "file":
        raise RuntimeError(f"unexpected GitHub response for {filename}")
    return base64.b64decode(record["content"], validate=False)


def main() -> None:
    client = boto3.client("lambda", region_name="us-east-2")
    current = client.get_function(FunctionName=FUNCTION)
    cfg = current["Configuration"]
    env = cfg.get("Environment", {}).get("Variables", {})
    token = env.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("existing Lambda GitHub token missing")
    assert cfg["Runtime"] == "python3.13" and cfg["Handler"] == "src.app.handler"
    assert client.get_function_configuration(FunctionName=FUNCTION, Qualifier="1")["Version"] == "1"
    response = requests.get(current["Code"]["Location"], timeout=40)
    response.raise_for_status()
    with tempfile.TemporaryDirectory(prefix="hd-mcp-build-") as temporary:
        stage = Path(temporary) / "stage"
        stage.mkdir()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for info in archive.infolist():
                target = (stage / info.filename).resolve()
                if not target.is_relative_to(stage.resolve()):
                    raise RuntimeError("invalid ZIP member path")
            archive.extractall(stage)
        original = (stage / "src/app.py").read_bytes()
        (stage / "execution_plane").mkdir(exist_ok=True)
        (stage / "execution_plane/__init__.py").write_text("", encoding="utf8")
        for filename in PATHS:
            (stage / "execution_plane" / filename).write_bytes(fetch_github_source(token, filename))
        # Install to the same isolated directory as production package, rather
        # than using the runner's dependencies. No changes to Lambda or its env.
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
            "--upgrade", "--target", str(stage),
            "mcp>=1.12,<2", "PyJWT[crypto]>=2.9,<3", "fastapi>=0.115,<1", "mangum>=0.19,<1",
        ], check=True, timeout=240)
        patched = original + b'\n\n# High Director V2 MCP opt-in integration\nfrom execution_plane.auth0_bootstrap import enable_auth0_mcp as _hd_enable_auth0_mcp\nhandler = _hd_enable_auth0_mcp(handler, __import__(__name__, fromlist=["*"]), settings=__import__("os").environ)\n'
        (stage / "src/app.py").write_bytes(patched)
        verification = r'''
import json, os
from src.app import handler
host = 'z2yacqwhvykeh32xasdps5jwdm0nzmqh.lambda-url.us-east-2.on.aws'
def invoke(path, method='GET', body=None, headers=None):
    return handler({
        'version':'2.0','routeKey':'$default','rawPath':path,'rawQueryString':'',
        'headers':{'host':host,**(headers or {})},
        'requestContext':{'accountId':'anonymous','apiId':'test','domainName':host,
          'http':{'method':method,'path':path,'protocol':'HTTP/1.1','sourceIp':'127.0.0.1','userAgent':'offline'},
          'requestId':'offline','routeKey':'$default','stage':'$default','time':'01/Jan/2026:00:00:00 +0000','timeEpoch':1767225600000},
        'isBase64Encoded':False,'body':json.dumps(body) if body is not None else None
    },{})
legacy = invoke('/openapi.json')
assert legacy['statusCode']==200, ('legacy',legacy['statusCode'])
body=json.loads(legacy['body'])
assert len(body.get('paths',{}))>=25, ('REST routes missing',len(body.get('paths',{})))
challenge=invoke('/director/mcp','POST',{'jsonrpc':'2.0','id':1,'method':'tools/list'},
    {'content-type':'application/json','accept':'application/json, text/event-stream'})
assert challenge['statusCode']==401, ('MCP should deny anonymous requests',challenge['statusCode'])
invalid=invoke('/director/mcp','POST',{'jsonrpc':'2.0','id':2,'method':'tools/list'},
    {'content-type':'application/json','accept':'application/json, text/event-stream','authorization':'Bearer invalid'})
assert invalid['statusCode']==401, ('MCP should deny invalid tokens',invalid['statusCode'])
print('PREFLIGHT OK: V1 OpenAPI routes preserved; MCP anonymous and malformed bearer requests denied')
'''
        child_env = dict(os.environ)
        child_env.update({
            "HD_AUTH0_ISSUER": "https://dev-b0akjdvpjmc382zz.us.auth0.com/",
            "HD_AUTH0_AUDIENCE": MCP_RESOURCE,
            "HD_AUTH0_CLIENT_ID": "hm4EFIG4tGsyLfm79IEVr916IAiyLG7y",
            "HD_AUTH0_OPERATOR_SUB": "auth0|6afa2afd2a905e5e8defe089",
            "GITHUB_TOKEN": "offline-fixture-token", "APP_API_KEY": "offline-fixture-key",
            "PYTHONPATH": str(stage),
        })
        subprocess.run([sys.executable, "-c", verification], cwd=stage, env=child_env, check=True, timeout=70)
        total = sum(f.stat().st_size for f in stage.rglob('*') if f.is_file())
        assert total < 240 * 1024 * 1024, 'MCP expanded ZIP package exceeds safe size threshold'
        print(f"MCP package build read-only preflight passed; staged bytes={total}, original Lambda code hash={cfg['CodeSha256']}; production unchanged")


if __name__ == '__main__':
    main()
