#!/usr/bin/env python3
"""Read scoped native orders through the existing company WeChat collector.

Use updated-order enumeration so older creations paid or shipped in the target
period are not discarded. Retain every original response. This is acquisition
only: an update query alone is not a released payment-coverage certificate.
"""
import argparse,copy,hashlib,importlib.util,json,os,sys,threading
from datetime import datetime
from pathlib import Path


def response_cache(paths):
    cache={};evidence=[]
    for path in paths:
        if not path.is_file():continue
        raw=path.read_bytes();lines=raw.splitlines(keepends=True);unfinished=False
        for index,line in enumerate(lines):
            try:record=json.loads(line)
            except json.JSONDecodeError:
                if index==len(lines)-1 and not line.endswith(b'\n'):
                    unfinished=True;continue
                raise ValueError('retained response contains a broken complete record')
            if not isinstance(record.get('response'),dict) or not record.get('observed_at'):
                raise ValueError('retained native response lacks provenance')
            key=record['endpoint'],json.dumps(record['request'],sort_keys=True)
            if key[0]=='/channels/ec/order/get' and str(record['response'].get('order',{}).get('order_id'))!=str(record['request']['order_id']):
                raise ValueError('retained response has a conflicting order identity')
            if key not in cache or record['observed_at']>cache[key]['observed_at']:cache[key]=record
        evidence.append(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),unfinished_last_record=unfinished))
    return cache,evidence


def retained_paths(resume,appid,start,endpoint):
    paths=[];seen=set()
    while resume:
        resume=Path(resume).resolve()
        if resume in seen:raise ValueError('acquisition resume lineage contains a cycle')
        seen.add(resume)
        metadata=json.loads((resume/'acquisition.json').read_text())
        if metadata['scope_start']!=start.isoformat() or metadata['started_at']!=endpoint.isoformat():
            raise ValueError('retained response lineage changed the source period')
        paths.append(resume/(appid+'.responses.jsonl'))
        resume=metadata.get('resumed_from')
    return list(reversed(paths))


def run(project,artifacts,start,resume=None,workers=8):
    spec=importlib.util.spec_from_file_location('crm_company_wechat_runner',project/'scripts/wechat_shop_scheduled_export.py')
    runner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=runner;spec.loader.exec_module(runner)
    exporter=runner.exporter
    lock=runner.acquire_platform_lock(runner.DEFAULT_PLATFORM_LOCK)
    if lock is None:raise RuntimeError('existing WeChat collection holds the shared platform lock')
    try:
        if artifacts.exists():raise ValueError('artifact directory exists; preserve it and select a new directory')
        artifacts.mkdir(parents=True,mode=0o700)
        runner.load_env_file(runner.DEFAULT_ENV_FILE)
        previous=json.loads((resume/'acquisition.json').read_text()) if resume else None
        if previous and previous['scope_start']!=start.isoformat():raise ValueError('resume cannot change the acquisition scope')
        endpoint=datetime.fromisoformat(previous['started_at']) if previous else datetime.now(exporter.CST).replace(microsecond=0)
        manifest={'started_at':endpoint.isoformat(),'scope_start':start.isoformat(),'status':'running','shops':[],
                  'workers':workers,'resumed_from':str(resume or ''),'executor_started_at':datetime.now(exporter.CST).isoformat()}
        manifest_path=artifacts/'acquisition.json'
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        manifest_path.chmod(0o600)
        for name,appid,secret_key in runner.STORES:
            completed=[s for s in previous['shops'] if s['shop_id']==appid] if previous else []
            if completed:
                retained=completed[0]
                for path_field,hash_field in [('output','output_sha256'),('responses','response_sha256')]:
                    if hashlib.sha256(Path(retained[path_field]).read_bytes()).hexdigest()!=retained[hash_field]:
                        raise ValueError('completed original changed before resume')
                for prior in retained.get('retained_response_artifacts',[]):
                    if hashlib.sha256(Path(prior['path']).read_bytes()).hexdigest()!=prior['sha256']:
                        raise ValueError('completed original response lineage changed')
                manifest['shops'].append(retained)
                manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
                print(json.dumps({'shop_id':appid,'status':'reused_completed_original'},ensure_ascii=False),flush=True)
                continue
            secret=os.environ.get(secret_key)
            if not secret:raise ValueError('existing native shop credential missing: '+name+' '+appid)
            auth_args=runner.AttrArgs(appid,secret)
            refresh=lambda:exporter.get_access_token(auth_args)
            client=exporter.Client(refresh(),refresh_access_token=refresh)
            response_path=artifacts/(appid+'.responses.jsonl')
            response_path.touch(mode=0o600,exist_ok=False)
            original_post=client.post;write_lock=threading.Lock();list_requests=set()
            prior_files=retained_paths(resume,appid,start,endpoint)
            cached,parent_evidence=response_cache(prior_files);reused={'list':0,'detail':0}

            def retained_post(path,payload):
                request_key=json.dumps(payload,sort_keys=True)
                if path=='/channels/ec/order/list/get':
                    if request_key in list_requests:raise RuntimeError('native list repeated its page cursor')
                    list_requests.add(request_key)
                saved=cached.get((path,request_key))
                if saved:
                    with write_lock:reused['list' if path.endswith('/list/get') else 'detail']+=1
                    return copy.deepcopy(saved['response'])
                data=original_post(path,payload)
                record={'endpoint':path,'request':payload,'observed_at':datetime.now(exporter.CST).isoformat(),'response':data}
                with write_lock:
                    with response_path.open('a',encoding='utf-8') as stream:
                        stream.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
                    response_path.chmod(0o600)
                if path=='/channels/ec/order/get' and str((data.get('order') or {}).get('order_id'))!=str(payload['order_id']):
                    raise ValueError('native order detail identity does not match its request')
                return data

            client.post=retained_post
            output=exporter.export_orders(client,artifacts,exporter.safe_part(name),appid,start,endpoint,start,True,workers,False,None,appid)
            evidence=json.loads(exporter.source_evidence_path(output).read_text())
            counts=evidence['summary']
            if counts['candidate_unique_orders']!=counts['detail_success_orders'] or counts['detail_failed_orders']:
                raise ValueError('native order enumeration and retrieved details differ: '+name)
            manifest['shops'].append({'shop_name':name,'shop_id':appid,'output':str(output),
                'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'responses':str(response_path),
                'response_sha256':hashlib.sha256(response_path.read_bytes()).hexdigest(),'summary':counts,
                'retained_response_artifacts':parent_evidence,'reused_response_counts':reused})
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            print(json.dumps({'shop_id':appid,'shop_name':name,**counts},ensure_ascii=False),flush=True)
        manifest.update(status='acquired',completed_at=datetime.now(exporter.CST).isoformat())
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8');manifest_path.chmod(0o600)
    except Exception as exc:
        if 'manifest_path' in locals():
            manifest.update(status='failed',failure_type=type(exc).__name__,failed_at=datetime.now(exporter.CST).isoformat())
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        raise
    finally:runner.release_platform_lock(lock)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--company-project',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True);parser.add_argument('--start',required=True)
    parser.add_argument('--resume',type=Path);parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    if not 1<=args.workers<=8:raise ValueError('use the existing exporter concurrency of at most eight workers')
    run(args.company_project,args.artifacts.resolve(),datetime.fromisoformat(args.start+'T00:00:00+08:00'),args.resume,args.workers)
