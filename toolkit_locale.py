"""Offline presentation localization. Never translate identifiers or save data."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
SUPPORTED=('en','zh-CN')
# API keys stay unchanged. These fields contain application-owned prose only.
DISPLAY_FIELDS=frozenset(('message','detail','reason','error','warning','warnings',
    'errors','notes','hint','help','description','action','title','recommendation',
    'limitations','risks','summary','label','note','post_load_note','scope','problem'))
DATA_FIELDS=frozenset(('name','path','source','output','filename','save','export',
    'line_name','station_name','train_name','schedule_name','project','id','code',
    'text','script','content','svg','geojson','coordinates','url','download_url'))


def normalize_language(value):
    return 'zh-CN' if str(value).lower() in ('zh','zh-cn','zh-hans') else 'en'


@lru_cache(maxsize=1)
def messages():
    return json.loads((ROOT/'web/locales/messages.en.json').read_text('utf-8'))


@lru_cache(maxsize=1)
def patterns():
    result=[]
    for source,target in messages().items():
        parts=re.split(r'(\{\{\d+\}\})',source)
        if len(parts)==1 or len(re.findall(r'[\u3400-\u9fff]',source))<4:continue
        regex=''.join('(.*?)' if re.fullmatch(r'\{\{\d+\}\}',p) else re.escape(p) for p in parts)
        result.append((len(source),re.compile('^'+regex+'$',re.DOTALL),target))
    return sorted(result,key=lambda row:row[0],reverse=True)


def translate_message(text,language='en'):
    if language!='en' or not isinstance(text,str):return text
    if text in messages():return messages()[text]
    if not re.search(r'[\u3400-\u9fff]',text):return text
    for _,pattern,target in patterns():
        match=pattern.fullmatch(text)
        if match:
            return re.sub(r'\{\{(\d+)\}\}',lambda m:match.group(int(m[1])+1),target)
    # Unknown messages remain intact rather than translating arbitrary player data.
    return text


def localize_payload(payload,language='en',field='',capability=False):
    if language!='en':return payload
    if isinstance(payload,dict):
        return {k:(v if k in DATA_FIELDS and not (capability and k=='name') else
                   localize_payload(v,language,k,capability or k=='capabilities')) for k,v in payload.items()}
    if isinstance(payload,list):return [localize_payload(v,language,field,capability) for v in payload]
    if isinstance(payload,str) and (field in DISPLAY_FIELDS or capability):return translate_message(payload,language)
    return payload
