"""Guarded one-Lambda MCP deployment. Only run after explicit authorization.

No credentials are logged or committed. Existing Lambda V1 routes, execution
role, Function URL, repository credentials and admin STS path are preserved.
Preflight is repeated before ANY Lambda mutation. Rollback is automatic.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

import boto3
import requests

from high_director_mcp_preflight import FUNCTION, PATHS, fetch_github_source

MCP_SETTINGS = ("HD_AUTH0_ISSUER", "HD_AUTH0_AUDIENCE", "HD_AUTH0_CLIENT_ID", "HD_AUTH0_OPERATOR_SUB")
REGION = "us-east-2"
HOST = "z2yacqwhvykeh32xasdps5jwdm0nzmqh.lambda-url.us-east-2.on.aws"


def await_ready(client, deadline_seconds=120):
    deadline=time.monotonic()+deadline_seconds
    while time.monotonic()<deadline:
        cfg=client.get_function_configuration(FunctionName=FUNCTION)
        if cfg.get('LastUpdateStatus')=='Successful' and cfg.get('State')=='Active':
            return cfg
        if cfg.get('LastUpdateStatus')=='Failed' or cfg.get('State')=='Failed':
            raise RuntimeError('Lambda update failed: '+str(cfg.get('LastUpdateStatusReasonCode','unknown')))
        time.sleep(3)
    raise TimeoutError('Lambda function did not become ready')


def event(path, method='GET', body=None, headers=None):
    return {
        'version':'2.0','routeKey':'$default','rawPath':path,'rawQueryString':'',
        'headers':{'host':HOST,**(headers or {})},
        'requestContext':{'accountId':'anonymous','apiId':'deploy-smoke','domainName':HOST,
            'http':{'method':method,'path':path,'protocol':'HTTP/1.1','sourceIp':'127.0.0.1','userAgent':'deploy-smoke'},
            'requestId':'deploy-smoke','routeKey':'$default','stage':'$default',
            'time':'01/Jan/2026:00:00:00 +0000','timeEpoch':1767225600000},
        'isBase64Encoded':False,
        'body':json.dumps(body) if body is not None else None,
    }


def assert_smoke_response(response, expected):
    actual=response.get('statusCode')
    if actual!=expected:
        raise RuntimeError(f'Lambda smoke status {actual}, expected {expected}')


def test_smoke(client):
    def invoke(evt):
        response=client.invoke(FunctionName=FUNCTION,InvocationType='RequestResponse',Payload=json.dumps(evt).encode('utf8'))
        if response.get('FunctionError'):
            raise RuntimeError('Lambda runtime invocation error during smoke test')
        body=json.loads(response['Payload'].read())
        if not isinstance(body,dict):
            raise RuntimeError('Lambda did not return Function URL response shape')
        return body

    legacy=invoke(event('/openapi.json'))
    assert_smoke_response(legacy,200)
    openapi=json.loads(legacy['body'])
    if len(openapi.get('paths',{}))<25:
        raise RuntimeError('Legacy REST OpenAPI routes missing after deploy')
    metadata_path='/.well-known/oauth-protected-resource/director/mcp'
    metadata=invoke(event(metadata_path))
    assert_smoke_response(metadata,200)
    resource=json.loads(metadata['body'])
    if resource.get('resource')!=os.environ['HD_AUTH0_AUDIENCE'] or resource.get('authorization_servers')!=[os.environ['HD_AUTH0_ISSUER']]:
        raise RuntimeError('OAuth discovery metadata does not match configured provider/resource')
    payload={'jsonrpc':'2.0','id':1,'method':'tools/list'}
    headers={'content-type':'application/json','accept':'application/json, text/event-stream'}
    assert_smoke_response(invoke(event('/director/mcp','POST',payload,headers)),401)
    assert_smoke_response(invoke(event('/director/mcp','POST',payload,{**headers,'authorization':'Bearer invalid'})),401)
    base='https://'+HOST
    public=requests.get(base+metadata_path,timeout=20)
    if public.status_code!=200 or public.json().get('resource')!=os.environ['HD_AUTH0_AUDIENCE']:
        raise RuntimeError('Public OAuth metadata discovery failed')
    public_legacy=requests.get(base+'/openapi.json',timeout=20)
    if public_legacy.status_code!=200:
        raise RuntimeError('Public legacy REST route failed')
    print('POST-DEPLOY SMOKE PASSED: REST API, RFC9728 discovery, denied missing/invalid tokens')


def build_package(archive_bytes, token, temp_root):
    stage=Path(temp_root)/'stage'
    stage.mkdir()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for info in archive.infolist():
            target=(stage/info.filename).resolve()
            if not target.is_relative_to(stage.resolve()):
                raise RuntimeError('unsafe ZIP entry path')
        archive.extractall(stage)
    app_path=stage/'src/app.py'
    original=app_path.read_bytes()
    if b'High Director V2 MCP opt-in integration' in original:
        raise RuntimeError('MCP wrapper already installed; refuse double patch')
    (stage/'execution_plane').mkdir(exist_ok=True)
    (stage/'execution_plane/__init__.py').write_bytes(b'')
    for filename in PATHS:
        (stage/'execution_plane'/filename).write_bytes(fetch_github_source(token,filename))
    subprocess.run([
        sys.executable,'-m','pip','install','--disable-pip-version-check','-q',
        '--upgrade','--target',str(stage),
        'mcp>=1.12,<2','PyJWT[crypto]>=2.9,<3','fastapi>=0.115,<1','mangum>=0.19,<1',
    ],check=True,timeout=240)
    app_path.write_bytes(original+b'\n\n# High Director V2 MCP opt-in integration\nfrom execution_plane.auth0_bootstrap import enable_auth0_mcp as _hd_enable_auth0_mcp\nhandler = _hd_enable_auth0_mcp(handler, __import__(__name__, fromlist=["*"]), settings=__import__("os").environ)\n')
    verify='''
import json
from src.app import handler
H='z2yacqwhvykeh32xasdps5jwdm0nzmqh.lambda-url.us-east-2.on.aws'
def event(p,m='GET',b=None,h=None):
 return {'version':'2.0','routeKey':'$default','rawPath':p,'rawQueryString':'','headers':{'host':H,**(h or {})},'requestContext':{'accountId':'anonymous','apiId':'offline','domainName':H,'http':{'method':m,'path':p,'protocol':'HTTP/1.1','sourceIp':'127.0.0.1','userAgent':'offline'},'requestId':'offline','routeKey':'$default','stage':'$default','time':'01/Jan/2026:00:00:00 +0000','timeEpoch':1767225600000},'isBase64Encoded':False,'body':json.dumps(b) if b is not None else None}
assert handler(event('/openapi.json'),{})['statusCode']==200
meta=handler(event('/.well-known/oauth-protected-resource/director/mcp'),{})
assert meta['statusCode']==200,meta['statusCode']
assert json.loads(meta['body'])['scopes_supported']==['director:admin']
body={'jsonrpc':'2.0','id':1,'method':'tools/list'}
heads={'content-type':'application/json','accept':'application/json, text/event-stream'}
assert handler(event('/director/mcp','POST',body,heads),{})['statusCode']==401
assert handler(event('/director/mcp','POST',body,{**heads,'authorization':'Bearer invalid'}),{})['statusCode']==401
'''
    subprocess.run([sys.executable,'-c',verify],cwd=stage,env={**os.environ,'GITHUB_OWNER':'warrengleeson','GITHUB_TOKEN':'offline-fixture','APP_API_KEY':'offline-fixture','PYTHONPATH':str(stage)},check=True,timeout=80)
    expanded=sum(f.stat().st_size for f in stage.rglob('*') if f.is_file())
    if expanded>=240*1024*1024:
        raise RuntimeError('Lambda expanded package near AWS size limit')
    package=io.BytesIO()
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for file in stage.rglob('*'):
            if file.is_file():
                output.write(file,file.relative_to(stage).as_posix())
    if package.tell()>48*1024*1024:
        raise RuntimeError('Lambda direct-upload package exceeds safe size threshold')
    print('COMPATIBILITY PREFLIGHT PASSED: old REST, MCP metadata, authorization denials and ZIP size')
    return package.getvalue()


def main():
    for key in MCP_SETTINGS:
        if not os.environ.get(key):
            raise RuntimeError('Required Auth0 deployment setting missing: '+key)
    client=boto3.client('lambda',region_name=REGION)
    current=client.get_function(FunctionName=FUNCTION)
    config=current['Configuration']
    old_env=dict(config.get('Environment',{}).get('Variables',{}))
    assert config['Handler']=='src.app.handler' and config['Runtime']=='python3.13'
    assert client.get_function_configuration(FunctionName=FUNCTION,Qualifier='1')['Version']=='1'
    github_token=old_env.get('GITHUB_TOKEN')
    if not github_token:
        raise RuntimeError('Live Lambda GitHub token not configured')
    original=requests.get(current['Code']['Location'],timeout=40)
    original.raise_for_status()
    old_zip=original.content
    with tempfile.TemporaryDirectory(prefix='hd-mcp-deployment-') as tmp:
        candidate=build_package(old_zip,github_token,tmp)
    # Re-check live revision immediately before first mutation.
    ready=await_ready(client)
    if ready['RevisionId']!=config['RevisionId'] or ready['CodeSha256']!=config['CodeSha256']:
        raise RuntimeError('Lambda changed since package retrieval; abort without mutation')
    # An immutable published version is a persistent rollback point even if the
    # runner exits. Existing version 1 is retained, never deleted.
    v1=client.get_function_configuration(FunctionName=FUNCTION,Qualifier='1')
    if v1['CodeSha256']!=config['CodeSha256']:
        snapshot=client.publish_version(FunctionName=FUNCTION,CodeSha256=config['CodeSha256'],RevisionId=config['RevisionId'],Description='High Director V1 rollback snapshot before Auth0 MCP rollout')
        print('PUBLISHED PRE-DEPLOY ROLLBACK VERSION '+snapshot['Version'])
        ready=await_ready(client)
    else:
        print('EXISTING IMMUTABLE ROLLBACK VERSION 1 MATCHES ORIGINAL CODE')
    updated=False
    try:
        new_env={**old_env,**{name:os.environ[name] for name in MCP_SETTINGS}}
        latest=client.get_function_configuration(FunctionName=FUNCTION)
        if latest['CodeSha256']!=config['CodeSha256']:
            raise RuntimeError('Concurrent Lambda code mutation detected; abort')
        client.update_function_configuration(FunctionName=FUNCTION,Environment={'Variables':new_env},RevisionId=latest['RevisionId'])
        updated=True
        latest=await_ready(client)
        if latest['CodeSha256']!=config['CodeSha256']:
            raise RuntimeError('Concurrent Lambda change during Auth0 configuration')
        client.update_function_code(FunctionName=FUNCTION,ZipFile=candidate,RevisionId=latest['RevisionId'],Publish=False)
        await_ready(client)
        test_smoke(client)
        print('MCP DEPLOYMENT COMPLETE. Published immutable rollback version 1 retained; V1 REST preserved.')
    except Exception:
        if updated:
            print('SMOKE FAILED: initiating automatic original-code and environment rollback')
            try:
                await_ready(client)
                client.update_function_code(FunctionName=FUNCTION,ZipFile=old_zip,Publish=False)
                await_ready(client)
                client.update_function_configuration(FunctionName=FUNCTION,Environment={'Variables':old_env})
                await_ready(client)
                print('AUTOMATIC ROLLBACK COMPLETE')
            except Exception as rollback_error:
                print('CRITICAL: automatic rollback did not complete: '+type(rollback_error).__name__)
        raise


if __name__=='__main__':
    main()
