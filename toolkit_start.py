"""No-console entry point for the novice Windows bundle and diagnostics."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import runpy
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))


def diagnose():
    result={'python':sys.version,'python_executable':sys.executable,'app':str(ROOT),'checks':[]}
    def test(name,fn):
        try:result['checks'].append({'name':name,'ok':True,'detail':str(fn())})
        except Exception as exc:result['checks'].append({'name':name,'ok':False,'detail':str(exc)})
    def zstd():
        from toolkit_binary import Zstd
        z=Zstd();data=b'NIMBY novice bundle test';assert z.decompress(z.compress(data))==data
        return '压缩及回读正常'
    def desktop():
        import webview
        import clr
        clr.AddReference('System.Windows.Forms')
        return '桌面组件可以加载；不等于已验证 WebView2 页面渲染'
    def node():
        from toolkit_autoroute import node_runtime
        path=node_runtime()
        if not path:raise RuntimeError('未找到自动铺轨运行库')
        return subprocess.check_output([path,'--version'],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=10).strip()
    def worker():
        proc=subprocess.run([sys.executable,str(ROOT/'toolkit_backend.py'),'--help'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=20)
        if proc.returncode:raise RuntimeError(proc.stderr.decode('utf-8',errors='replace')[-1000:])
        return '后台进程入口正常'
    test('存档压缩运行库',zstd);test('桌面窗口组件',desktop);test('自动铺轨 Node.js',node);test('独立后台进程',worker)
    test('网页资源',lambda: all((ROOT/p).is_file() for p in ('web/index.html','web/app.js','third_party/autotrack/tiles.mjs')) or (_ for _ in ()).throw(RuntimeError('资源缺失')))
    result['ok']=all(c['ok'] for c in result['checks'])
    return result


def readable_report(result, language='zh-CN'):
    if language == 'en':
        from toolkit_locale import translate_message
        lines=['NIMBY Timetable Toolkit — Diagnostic report',
               'Result: '+('Basic checks passed' if result['ok'] else 'Issues found; review failed checks'), '',
               'These checks do not modify game saves or certify in-game operation.',
               'If the window still fails to open, include a screenshot and startup.log.', '']
        for check in result['checks']:
            lines.extend([('PASS' if check['ok'] else 'FAIL')+': '+translate_message(check['name']),
                          '  '+translate_message(check['detail'])])
        lines.extend(['','Application: '+result['app'],'Runtime: '+result['python_executable'],
                      'Python: '+result['python'],'','Review private usernames and paths before sharing this report.'])
        return '\n'.join(lines)+'\n'
    lines=['NIMBY 工具箱 · 故障诊断报告',
           '结果：'+('基础检查全部通过' if result['ok'] else '发现问题，请查看下面标记为“失败”的项目'),
           '', '这些检查不会修改游戏存档，也不代表所有游戏功能已经验收。',
           '若窗口仍打不开，请同时提供问题截图和 startup.log。', '']
    for check in result['checks']:
        lines.extend([('通过' if check['ok'] else '失败')+'：'+check['name'], '  '+check['detail']])
    lines.extend(['', '工具箱位置：'+result['app'], '运行库位置：'+result['python_executable'],
                  'Python：'+result['python'], '', '发送报告前，请检查路径中是否含有不想公开的用户名。'])
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--diagnose',action='store_true');parser.add_argument('--self-test',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    logs=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'NIMBY_Timetable_Toolkit'/'logs'
    try:
        language=json.loads((logs.parent/'settings.json').read_text('utf-8-sig')).get('language','en')
    except (OSError,ValueError):language='en'
    logs.mkdir(parents=True,exist_ok=True)
    log=logs/'startup.log'
    # Bounded rotation, preserves the previous startup rather than growing forever.
    if log.exists() and log.stat().st_size>2_000_000:log.replace(log.with_suffix('.previous.log'))
    sys.stdout=sys.stderr=log.open('a',encoding='utf-8',buffering=1)
    print('\n启动',datetime.now().isoformat(),str(ROOT))
    try:
        if args.diagnose or args.self_test:
            result=diagnose()
            report=args.report or logs/('diagnostics-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.txt')
            report.parent.mkdir(parents=True,exist_ok=True)
            report.write_text(json.dumps(result,ensure_ascii=False,indent=2) if args.self_test else readable_report(result,language),encoding='utf-8-sig')
            if args.diagnose and not args.self_test and os.name=='nt':os.startfile(report)
            return 0 if result['ok'] else 1
        sys.argv=[str(ROOT/'toolkit_webapp.py')]
        runpy.run_path(sys.argv[0],run_name='__main__')
        return 0
    except Exception:
        traceback.print_exc()
        if os.name=='nt' and not args.self_test:
            message=('启动遇到问题。请运行“故障诊断.exe”。\n日志位置：' if language=='zh-CN' else
                     'Startup failed. Run Diagnostics.exe.\nLog: ')
            ctypes.windll.user32.MessageBoxW(None,message+str(log),'NIMBY Timetable Toolkit',0x10)
        return 1


if __name__=='__main__':raise SystemExit(main())
