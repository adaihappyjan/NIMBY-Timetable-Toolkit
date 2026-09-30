"""Build a Windows x64, offline, no-system-Python desktop release.

Build-time downloads only, pinned to official URLs and SHA-256 in the lockfile.
No setup.py/pip/installer execution: unpack vetted wheels and the one pure-source
proxy_tools dependency. Runtime copies are per-user and content-addressed so the
updater never needs to replace an interpreter which is currently in use.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import Request,urlopen

from build_portable import ROOT,build_portable


def digest(data):return hashlib.sha256(data).hexdigest()


def download(spec,cache):
    name=spec['url'].rsplit('/',1)[-1];path=cache/name
    if path.is_file():
        data=path.read_bytes()
        if digest(data)==spec['sha256']:return data
        raise RuntimeError(f'缓存校验失败：{path}；请移走此文件再重新构建')
    print('Download',name,flush=True)
    with urlopen(Request(spec['url'],headers={'User-Agent':'NIMBY-Toolkit-Builder'}),timeout=90) as response:
        data=response.read(100_000_001)
    if len(data)>100_000_000 or digest(data)!=spec['sha256']:raise RuntimeError(f'官方下载 SHA-256 校验失败：{name}')
    cache.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as output:output.write(data)
    return data


def safe_name(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '\\' in name or ':' in name or any(part in ('','..','.') for part in name.split('/')):raise ValueError('不安全的归档路径')
    return p.as_posix()


def runtime_entries(lock,cache):
    entries={}
    with zipfile.ZipFile(io.BytesIO(download(lock['python'],cache))) as z:
        for entry in z.infolist():
            if not entry.is_dir():entries['python/'+safe_name(entry.filename)]=z.read(entry)
    # Isolated interpreter: packaged stdlib and dependencies only. Every toolkit
    # subprocess entry explicitly adds its own source root, not the system PATH.
    entries['python/python313._pth']=b'python313.zip\n.\nLib/site-packages\nimport site\n'
    for spec in lock['wheels']:
        data=download(spec,cache)
        if spec['filename'].endswith('.whl'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for entry in z.infolist():
                    if entry.is_dir():continue
                    name=safe_name(entry.filename)
                    if '.data/scripts/' in name:continue  # optional CLI entry, no desktop dependency
                    if '.data/' in name:raise RuntimeError('请审核新 wheel 的 .data 布局：'+name)
                    dest='python/Lib/site-packages/'+name
                    if dest in entries:raise RuntimeError('依赖文件重名：'+dest)
                    entries[dest]=z.read(entry)
        elif spec['name']=='proxy-tools':
            # This project publishes no wheel. Copy pure Python source + license,
            # never execute an arbitrary build/install hook from the archive.
            copied=False
            with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
                for member in archive.getmembers():
                    if not member.isfile():continue
                    name=safe_name(member.name).split('/',1)[-1]
                    if name.startswith('proxy_tools/') and name.endswith('.py'):
                        entries['python/Lib/site-packages/'+name]=archive.extractfile(member).read();copied=True
                    elif name in ('LICENSE','LICENSE.txt','PKG-INFO'):
                        entries['licenses/proxy-tools/'+name]=archive.extractfile(member).read()
            if not copied:raise RuntimeError('proxy_tools 发行布局已变化')
        else:raise RuntimeError('不支持的运行库文件')
    with zipfile.ZipFile(io.BytesIO(download(lock['node'],cache))) as z:
        for filename in ('node.exe','LICENSE'):
            full=f"node-v{lock['node']['version']}-win-x64/{filename}"
            entries['node.exe' if filename=='node.exe' else 'licenses/Node-LICENSE.txt']=z.read(full)
    entries['licenses/runtime-sources.json']=json.dumps(lock,indent=2).encode()
    return entries


def make_runtime(entries):
    manifest={name:digest(data) for name,data in sorted(entries.items())}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(safe_name(name),(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
        z.writestr(zipfile.ZipInfo('runtime-manifest.json',(2026,1,1,0,0,0)),json.dumps(manifest,sort_keys=True).encode())
    return out.getvalue()


def compile_launchers(runtime,temp):
    compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():raise RuntimeError('构建需要 Windows .NET Framework C# 编译器；最终用户不需要它')
    code=(ROOT/'scripts/NoviceLauncher.cs').read_text('utf-8').replace('@@RUNTIME_SHA256@@',digest(runtime))
    source=temp/'Launcher.cs';source.write_text(code,encoding='utf-8-sig')
    result={}
    for filename,define in [('NIMBYToolkit.exe',[]),('故障诊断.exe',['/define:DIAGNOSTIC'])]:
        exe=temp/filename
        subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
            '/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll',
            '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
            '/out:'+str(exe),*define,str(source)],check=True)
        result[filename]=exe.read_bytes()
    return result


def build(version,output,cache):
    if os.name!='nt':raise RuntimeError('零基础 EXE 包须在 Windows x64 上构建')
    lock=json.loads((ROOT/'scripts/novice-runtime.lock.json').read_text('utf-8'))
    runtime=make_runtime(runtime_entries(lock,cache))
    with tempfile.TemporaryDirectory(prefix='nimby-launcher-') as temp:
        extras=compile_launchers(runtime,Path(temp))
    extras['runtime/runtime.zip']=runtime
    archive,sums=build_portable(version,output,extras=extras)
    if archive.stat().st_size>100_000_000:raise RuntimeError('包超过旧版更新器的 100 MB 上限，不可发布')
    print(archive,flush=True);print(sums,flush=True)
    return archive,sums


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='构建无需安装 Python/Node.js 的零基础 EXE 包')
    parser.add_argument('--version',required=True);parser.add_argument('--output',type=Path,default=ROOT/'dist/novice')
    parser.add_argument('--cache',type=Path,default=ROOT/'dist/novice-downloads')
    args=parser.parse_args();build(args.version,args.output.resolve(),args.cache.resolve())
