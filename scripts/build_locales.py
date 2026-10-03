"""Build offline English assets from the maintained source-message catalog.

Only project-owned literal text is translated. Interpolated data, object keys,
regular expressions, HTML values and application logic are never translated.
"""
from __future__ import annotations

import argparse
import ast
import html
import json
import os
from pathlib import Path
import re
import subprocess
import hashlib

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r'[\u3400-\u9fff]')
# Preserve tags, entity references, placeholders, paths and all Latin identifiers.
# Chinese phrase units are shared across HTML, JS and backend diagnostics.
PHRASE = re.compile(r'[\u3400-\u9fff]+(?:[，、：；。！？（）「」“”《》·/ +—–…\dA-Za-z.%：-]*[\u3400-\u9fff]+)*')


def units(text):
    return [m.group(0) for m in PHRASE.finditer(text)]


def javascript_spans(path):
    result = subprocess.run(['node',str(ROOT/'scripts/locale_inventory.cjs'),str(path)],
                            check=True,capture_output=True,encoding='utf-8')
    return json.loads(result.stdout)


def inventory():
    sources = {}
    for path in sorted((ROOT/'web').glob('*.js')):
        if path.name == 'locale.js':
            continue
        for span in javascript_spans(path):
            for text in units(span['text']):
                sources.setdefault(text,set()).add('web/'+path.name)
    # Only text nodes and display attributes, never input values or data-* values.
    markup = (ROOT/'web/index.html').read_text('utf-8')
    for text in re.findall(r'>([^<>]+)<|(?:title|placeholder|aria-label)="([^"]*)"',markup):
        for value in text:
            for unit in units(value):sources.setdefault(unit,set()).add('web/index.html')
    for path in sorted(ROOT.glob('toolkit_*.py')):
        if path.name == 'toolkit_locale.py':continue
        tree = ast.parse(path.read_text('utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and HAN.search(node.value):
                for unit in units(node.value):sources.setdefault(unit,set()).add(path.name)
    return {k:sorted(v) for k,v in sorted(sources.items())}


def translate(text, catalog):
    # Complete phrases whose English word order differs around Latin terms.
    full = {
        '全程只用存档，不需要导出 JSON': 'Uses only the save—no JSON export required',
        '离线预览 · 无需时刻表 JSON': 'Offline preview · No timetable JSON required',
        '语言 / Language': 'Language',
        'Language / 语言': 'Language',
    }
    if text in full: return full[text]
    def replace(match):
        source=match.group(0)
        if source not in catalog:raise ValueError(f'Missing English translation: {source}')
        value=catalog[source]
        # Keep surrounding Latin identifiers and interpolations separate from prose.
        if match.start() and text[match.start()-1].isascii() and text[match.start()-1].isalnum():value=' '+value
        if match.end()<len(text) and text[match.end()].isascii() and text[match.end()].isalnum():value+=' '
        return value
    result=PHRASE.sub(replace,text)
    if HAN.search(text):
        result=result.translate(str.maketrans({'。':'.','，':', ','：':': ','；':'; ','（':'(','）':')','、':', ','？':'?','！':'!'}))
        result=re.sub(r'([.!?])\.',r'\1',result)
        result=re.sub(r'([?!])\1+',r'\1',result)
        result=re.sub(r'\.(?=[A-Z])', '. ', result)
    return result


def translate_markup(text,catalog):
    # Do not rewrite HTML attributes carrying application data or JavaScript.
    text=re.sub(r'(>)([^<>]+)(<)',lambda m:m[1]+translate(m[2],catalog)+m[3],text)
    return re.sub(r'((?:title|placeholder|aria-label)=")([^"]*)(")',
                  lambda m:m[1]+html.escape(translate(html.unescape(m[2]),catalog),quote=True)+m[3],text)


def build(catalog):
    output=ROOT/'web/locales/en'
    output.mkdir(parents=True,exist_ok=True)
    hashes={}
    for path in sorted((ROOT/'web').glob('*.js')):
        if path.name=='locale.js':continue
        source=path.read_text('utf-8')
        edits=[]
        for span in javascript_spans(path):
            value=translate(span['text'],catalog)
            if span['kind']=='string':value=json.dumps(value,ensure_ascii=False)
            else:
                if span['text'] and HAN.match(span['text']) and span['start'] and source[span['start']-1]=='}':value=' '+value
                if span['text'] and HAN.search(span['text'][-1:]) and source[span['end']:].startswith('${'):value+=' '
                value=value.replace('\\','\\\\').replace('`','\\`').replace('${','\\${')
            edits.append((span['start'],span['end'],value))
        for start,end,value in sorted(edits,reverse=True):source=source[:start]+value+source[end:]
        (output/path.name).write_text(source,encoding='utf-8',newline='\n')
        hashes[path.name]=hashlib.sha256(path.read_text('utf-8').encode()).hexdigest()
    path=ROOT/'web/index.html'
    source=translate_markup(path.read_text('utf-8'),catalog).replace('lang="zh-CN"','lang="en"',1)
    source=re.sub(r'(<option value="zh-CN"[^>]*>).*?(</option>)',r'\1简体中文\2',source)
    # Only toolkit-owned initial defaults, never loaded player input values.
    source=source.replace('id="plan-name" value="新线路 Daily"','id="plan-name" value="New line Daily"')
    source=source.replace('id="binder-name" value="批量运营扩展包"','id="binder-name" value="Batch operations extensions"')
    source=source.replace('alt="adaihappyjan 的头像"','alt="Portrait of adaihappyjan"')
    source=re.sub(r'([.!?])(?=<(?:b|strong)>)',r'\1 ',source)
    source=re.sub(r'(</(?:b|strong)>)(?=[A-Za-z])',r'\1 ',source)
    (output/path.name).write_text(source,encoding='utf-8',newline='\n')
    hashes[path.name]=hashlib.sha256(path.read_text('utf-8').encode()).hexdigest()
    (output/'sources.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
    # Full-message templates let the API translate prose without touching values
    # interpolated from player files. Captures are reinserted byte-for-byte.
    messages={}
    for path in sorted(ROOT.glob('toolkit_*.py')):
        if path.name=='toolkit_locale.py':continue
        for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and HAN.search(node.value):
                messages[node.value]=translate(node.value,catalog)
            elif isinstance(node,ast.JoinedStr):
                parts=[];count=0
                for value in node.values:
                    if isinstance(value,ast.Constant):parts.append(value.value)
                    else:parts.append('{{'+str(count)+'}}');count+=1
                text=''.join(parts)
                if HAN.search(text):messages[text]=translate(text,catalog)
    (ROOT/'web/locales/messages.en.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Built {len(hashes)} English assets and {len(messages)} diagnostic messages.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inventory',action='store_true')
    args=parser.parse_args()
    if args.inventory:
        print(json.dumps(inventory(),ensure_ascii=False,indent=2))
        return
    catalog=json.loads((ROOT/'web/locales/en.json').read_text('utf-8'))
    override=ROOT/'web/locales/en.overrides.json'
    if override.exists():catalog.update(json.loads(override.read_text('utf-8')))
    build(catalog)


if __name__ == '__main__':main()
