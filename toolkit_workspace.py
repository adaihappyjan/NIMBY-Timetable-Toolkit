"""Project workspace: conservative planning, batch edits and source-backed audits.

All simulation reports describe exported plans, never live track occupancy.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import re
import threading
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

WEEK = 604800
STORE_LOCK = threading.RLock()


def fingerprint(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('文件正在变化，请等待游戏保存或导出完成后重试。')
    return digest.hexdigest()


def atomic_store(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def project_state(root: Path, key: str, patch: dict | None = None) -> dict:
    # Keys are opaque, paths supplied by clients never become filesystem paths.
    path = root / 'projects' / (hashlib.sha256(key.encode()).hexdigest() + '.json')
    with STORE_LOCK:
        value = json.loads(path.read_text('utf-8')) if path.exists() else {}
        if patch is not None:
            if not isinstance(patch, dict) or len(json.dumps(patch)) > 900000:
                raise ValueError('草稿过大或格式无效')
            value.update(patch)
            atomic_store(path, value)
        return value


def read_save(path: Path):
    from toolkit_binary import split_save, Zstd
    mark = fingerprint(path)
    header, frame, offset = split_save(path)
    raw = Zstd().decompress(frame)
    if fingerprint(path) != mark:
        raise ValueError('读取期间存档已更新，请重新读取。')
    return mark, header, raw, offset


def catalog(path: Path) -> dict:
    import toolkit_scheduleconfig as sc
    from toolkit_savereader import read_schedule_assignments, read_trains_from_raw
    mark, header, raw, _ = read_save(path)
    groups = sc.read_operating_groups(raw)
    assignments = {a.schedule_id: a for a in read_schedule_assignments(raw)}
    trains = {t.id: t.name for t in read_trains_from_raw(raw)}
    lines = sc.read_operating_lines(raw, groups)
    rows = []
    for g in groups:
        row = sc.group_to_dict(g)
        row['kind'] = 'template' if len(g.entries) == 1 and g.entries[0].line_id == g.group_line_id else 'timetable'
        a = assignments.get(g.schedule_id)
        row['trains'] = [{'id': t, 'name': trains.get(t, t)} for t in sorted(set(a.train_ids if a else []))]
        rows.append(row)
    from toolkit_binary import save_version_info
    return {'save': str(path), 'fingerprint': mark, 'groups': rows,
            'game_version': save_version_info(header),
            'counts': {'objects': len(rows), 'templates': sum(r['kind'] == 'template' for r in rows),
                       'timetables': sum(r['kind'] == 'timetable' for r in rows), 'trains': len(trains)},
            'lines': [{'id': l.line_id, 'name': l.name, 'stop_count': l.stop_count,
                       'selectors': [{'station_id': s.station_id, 'station_name': s.station_name,
                                      'route_index': s.route_index, 'selector': s.selector} for s in l.selectors]} for l in lines]}


def finite(value, low=0, high=172800) -> float:
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high or result * 2 != round(result * 2):
        raise ValueError(f'时间必须在 {low}–{high} 秒内，精确到 0.5 秒')
    return result


def preset_updates(group: dict, options: dict, lines: list[dict]) -> dict:
    """Edit existing orders; do not guess which line/depot a fleet should use."""
    entries = group['entries']
    line_map = {l['id']: l for l in lines}
    depot_ids = set(options.get('depot_ids') or [])
    if not depot_ids <= set(line_map):
        raise ValueError('所选车库线路不在当前存档中')
    days = options.get('days_mask')
    if days is not None and (type(days) is not int or not 1 <= days <= 127):
        raise ValueError('请勾选至少一个运营日')
    service = [i for i, e in enumerate(entries) if e['line_id'] not in depot_ids and line_map.get(e['line_id'], {}).get('stop_count', 0) > 1]
    depots = [i for i, e in enumerate(entries) if e['line_id'] in depot_ids]
    if options.get('service_start') is not None and len(service) != 1:
        raise ValueError(f"{group['schedule_name']} 有 {len(service)} 条客运指令；请在编排器明确每段时间，不能自动猜测首班。")
    if options.get('depot_time') is not None and len(depots) != 1:
        raise ValueError(f"{group['schedule_name']} 未唯一匹配一条已选车库指令；请先选择正确车库。")
    updates = {}
    for i, e in enumerate(entries):
        row = {}
        if days is not None:
            if e.get('stacked_entries'):
                raise ValueError('含堆积指令的星期修改请使用完整编排器，避免漏改子项。')
            row['days_mask'] = days
        if i in service and options.get('service_start') is not None:
            row['time_seconds'] = finite(options['service_start'])
        if i in depots:
            row.update(repeat_count=1, repeat_is_max=False)
            if options.get('depot_time') is not None:
                row['time_seconds'] = finite(options['depot_time'])
        if row:
            updates[i] = row
    distributions = {}
    if options.get('interval') is not None:
        interval = finite(options['interval'], 0.5, 86400)
        for i in service:
            index = entries[i]['offset_group_index']
            if any(entries[d]['offset_group_index'] == index for d in depots):
                raise ValueError('客运与车库共用偏移组；请在编排器分组后再修改，避免改变入库分布。')
            distributions[index] = {'mode': 'fixed', 'fixed_interval_seconds': interval}
    if not updates and not distributions:
        raise ValueError('尚未选择要修改的字段')
    return {'entry_updates': updates, 'distribution_updates': distributions}


def period_preset(group: dict, options: dict, lines: list[dict]) -> dict:
    """Explicit start-boundary orders. End-of-service stays the existing depot order.

    Fixed offsets are not interpreted as a guaranteed sustained line headway.
    """
    periods = options.get('periods') or []
    if not 1 <= len(periods) <= 8:
        raise ValueError('分时段预设需包含 1–8 个时间边界')
    depot_ids = set(options.get('depot_ids') or [])
    services = [e for e in group['entries'] if e['line_id'] not in depot_ids and next((l['stop_count'] for l in lines if l['id']==e['line_id']),0)>1]
    if len(services)!=1 or any(e.get('stacked_entries') for e in group['entries']):
        raise ValueError('分时段快捷生成只支持一条客运指令且没有堆积子项的表；复杂表请使用完整编排器')
    if not any(e['line_id'] in depot_ids for e in group['entries']):
        raise ValueError('分时段预设必须确认已有回库指令，不能自动猜测运营结束方式')
    # Existing user fields and all persisted order IDs are retained.
    base_options = {**options, 'interval': None, 'service_start': None}
    base = preset_updates(group, base_options, lines)
    plan = copy.deepcopy(group['entries'])
    for i, fields in base['entry_updates'].items():
        plan[i].update(fields)
    source = next(e for e in plan if e['order_id']==services[0]['order_id'])
    times = [finite(p['start']) for p in periods]
    if times != sorted(set(times)):
        raise ValueError('时段边界必须递增且不能重复（次日时间使用 24:00–48:00）')
    used = {e['offset_group_index'] for e in plan if e is not source}
    available = [i for i in range(10) if i not in used]
    if len(available)<len(periods):
        raise ValueError('没有足够的空闲偏移组来隔离各客运时段和车库')
    distributions = {}
    template = copy.deepcopy(source)
    for index, period in enumerate(periods):
        entry = source if index==0 else copy.deepcopy(template)
        if index:
            entry['order_id']=None
            plan.append(entry)
        entry.update(time_seconds=times[index], offset_group_index=available[index],
                     repeat_is_max=True, repeat_count=None, continue_into_next=True)
        distributions[available[index]]={'mode':'fixed','fixed_interval_seconds':finite(period['interval'],.5,86400)}
    plan.sort(key=lambda e:e['time_seconds'])
    return {'entry_plan':plan,'distribution_updates':distributions}


def batch(path: Path, request: dict) -> dict:
    import toolkit_scheduleconfig as sc
    from toolkit_backend import write_output, emit_progress
    emit_progress('workspace',5,100,'正在读取当前存档并核对预览指纹…')
    current = catalog(path)
    if request.get('fingerprint') != current['fingerprint']:
        raise ValueError('存档与预览指纹不一致，请重新读取和预览；未写入。')
    selected = request.get('selected') or []
    if not 1 <= len(selected) <= 100 or len(selected) != len(set(selected)):
        raise ValueError('请选择 1–100 张不同的运营表')
    mark, header, raw, offset = read_save(path)
    if mark != current['fingerprint']:
        raise ValueError('存档已更新，请重新预览')
    patched = raw
    changes = []
    for n, sid in enumerate(selected):
        g = next((g for g in current['groups'] if g['schedule_id'] == sid), None)
        if not g or g['kind'] != 'timetable':
            raise ValueError('批量预设只作用于独立运营表，不修改线路模板')
        emit_progress('workspace',15+int(n*60/len(selected)),100,f"正在校验 {n+1}/{len(selected)}：{g['schedule_name']}")
        options=request.get('preset', {})
        updates = period_preset(g, options, current['lines']) if options.get('periods') else preset_updates(g, options, current['lines'])
        patched, before, after, fields = sc.set_operating_group(patched, sid, **updates)
        changes.append({'schedule_id': sid, 'name': g['schedule_name'], 'before': sc.group_to_dict(before),
                        'after': sc.group_to_dict(after), 'fields': fields})
    manifest = {'action': 'workspace-batch', 'changes': changes, 'source_fingerprint': mark,
                'game_loaded': False, 'operation_verified': False,
                'scope': '运营指令结构校验；不包含游戏寻路、轨道占用和实际调度验证'}
    if fingerprint(path) != mark:
        raise ValueError('处理期间存档发生变化，请重新预览')
    if not request.get('apply'):
        return {**manifest, 'preview': True, 'fingerprint': mark}
    preview_hash = hashlib.sha256(json.dumps(changes, sort_keys=True).encode()).hexdigest()
    if request.get('preview_hash') != preview_hash:
        raise ValueError('方案已经改变或没有预览，请先重新预览')
    return write_output(path, Path(request['output']), header, raw, patched, manifest, offset, 3)


def _pair_one(args):
    save, export = map(Path, args)
    from toolkit_backend import validate_save_export, load_objects
    try:
        sm, _, raw, _ = read_save(save)
        em = fingerprint(export)
        check = validate_save_export(raw, load_objects(export))
        if em != fingerprint(export) or sm != fingerprint(save):
            raise ValueError('文件在检查期间改变')
        return {'path': str(export), 'matched': True, 'fingerprint': em, 'check': check}
    except Exception as exc:
        return {'path': str(export), 'matched': False, 'reason': str(exc)}


def pair_exports(save: Path, exports: list[str], workers=1) -> dict:
    # Two decompressed saves maximum by default; large saves automatically serialize.
    count = max(1, min(workers, 2, 32 * 1024 * 1024 // max(1, save.stat().st_size)))
    jobs = [(str(save), e) for e in exports[:12]]
    if count > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=count) as pool:
            rows = list(pool.map(_pair_one, jobs))
    else:
        rows = [_pair_one(j) for j in jobs]
    return {'pairs': rows, 'workers_used': count, 'candidate_limit': 12,
            'note': '仅表示结构兼容，不能证明导出时间相同；写入前仍重新校验。'}


def plan_runs(objects: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    lines = {o['id']: o for o in objects if o.get('class') == 'Line'}
    trains = defaultdict(list)
    issues = []
    for schedule in (o for o in objects if o.get('class') == 'Schedule'):
        shifts = {s['id']: s for s in schedule.get('shifts', [])}
        for tid, assigned in (schedule.get('trains') or {}).items():
            for shift_id in assigned:
                if shift_id not in shifts:
                    issues.append({'train': tid, 'problem': '导出缺少已分配班次', 'status': 'unknown'})
                    continue
                for run in shifts[shift_id].get('runs', []):
                    times = run.get('arrival_departure') or []
                    line = lines.get(run.get('line_id'), {})
                    stops = line.get('stops') or []
                    if not times or len(times) % 2 or not stops:
                        issues.append({'train': tid, 'problem': '缺少完整时分或站点', 'status': 'unknown'})
                        continue
                    a, b = run.get('enter_stop_idx', 0), run.get('exit_stop_idx', len(stops)-1)
                    if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a < len(stops) or not 0 <= b < len(stops):
                        issues.append({'train': tid, 'problem': '进出站索引无法解释', 'status': 'unknown'})
                        continue
                    start, end = times[0], times[-1]
                    if end < start:
                        issues.append({'train': tid, 'problem': '结束时间早于开始时间', 'status': 'error'})
                        continue
                    trains[tid].append({'start': start, 'end': end, 'from': stops[a].get('station_id'),
                                        'to': stops[b].get('station_id'), 'line': run['line_id'],
                                        'schedule': schedule.get('name', schedule['id'])})
    return trains, issues, list(lines.values())


def continuity(objects: list[dict], depots: dict | None = None) -> dict:
    trains, issues, _ = plan_runs(objects)
    depots = depots or {}
    occupancy = defaultdict(list)
    coverage = []
    without_depot = []
    for tid, runs in trains.items():
        runs.sort(key=lambda r: r['start'])
        coverage.append({'train': tid, 'days': sorted({int(r['start'] // 86400) % 7 for r in runs}), 'runs': len(runs)})
        if depots and not any(r['line'] in depots for r in runs):
            without_depot.append(tid)
        # Compare the last run to the next weekly occurrence of the first.
        pairs = list(zip(runs, runs[1:]))
        if runs:
            nxt = dict(runs[0]); nxt['start'] += WEEK; nxt['end'] += WEEK
            pairs.append((runs[-1], nxt))
        for a, b in pairs:
            gap = b['start'] - a['end']
            if gap < 0:
                issues.append({'train': tid, 'time': b['start'], 'problem': '班次重叠', 'seconds': -gap, 'status': 'error'})
            elif not a['to'] or a['to'] != b['from']:
                issues.append({'train': tid, 'time': b['start'], 'problem': '异站接续：空驶时长与进路未验证', 'seconds': gap, 'status': 'unknown'})
            if a['line'] in depots and gap >= 0:
                # Arrival at the depot until next planned departure; split weekly wrap.
                start, end = a['start'], b['start']
                if end - start > WEEK:
                    issues.append({'train': tid, 'problem': '车库区间超过一周，未计入容量', 'status': 'unknown'})
                    continue
                start %= WEEK; end = start + (b['start'] - a['start'])
                if end > WEEK:
                    occupancy[a['line']].extend([(start, WEEK, tid), (0, end-WEEK, tid)])
                else:
                    occupancy[a['line']].append((start, end, tid))
    depot_rows = []
    for lid, capacity in depots.items():
        capacity = int(capacity)
        if not 1 <= capacity <= 10000:
            raise ValueError('车库容量需为 1–10000')
        events = sorted((t, delta, tid) for s, e, tid in occupancy[lid] if e > s for t, delta in ((s, 1), (e, -1)))
        active = Counter(); peak = 0; timeline = []
        for t, delta, tid in events:
            active[tid] += delta
            count = sum(v > 0 for v in active.values()); peak = max(peak, count)
            timeline.append({'time': t, 'occupied': count})
        depot_rows.append({'line': lid, 'capacity': capacity, 'planned_peak': peak if events else None, 'over_capacity': peak > capacity if events else None,
                           'timeline': timeline, 'intervals': occupancy[lid]})
    no_plan = [o['id'] for o in objects if o.get('class')=='Train' and o['id'] not in trains]
    return {'issues': issues, 'coverage': coverage, 'depots': depot_rows, 'without_depot': without_depot, 'without_plan': no_plan,
            'scope': '导出的一周计划：含周日至周一；未验证空驶最短时长、站台、轨道占用和实际回库。空白日不自动判错。'}


def corridor(branches: list[dict], windows: list[dict]) -> dict:
    if not 2 <= len(branches) <= 8 or not 1 <= len(windows) <= 8:
        raise ValueError('请选择 2–8 条支线和 1–8 个时段')
    # A directed pair of station IDs avoids same-name and opposing-direction false matches.
    segments = [set(zip(b['stations'], b['stations'][1:])) for b in branches]
    common = set.intersection(*segments)
    if len(common) != 1:
        raise ValueError('请明确选择相同方向的一对共线入口站；不能用同名站或猜测环线方向。')
    edge = next(iter(common))
    if any(list(zip(b['stations'], b['stations'][1:])).count(edge) != 1 for b in branches):
        raise ValueError('该入口区间在线路内重复出现；请先明确运行方向和经过次数。')
    events = []
    ranges = []
    for window in windows:
        start = finite(window['start']); end = finite(window['end'])
        if end <= start:
            end += 86400
        if any(start < e and s < end for s, e in ranges):
            raise ValueError('时段重叠，请先调整边界')
        ranges.append((start, end))
        for branch in branches:
            interval = finite(window['intervals'][branch['id']], 10, 86400)
            phase = finite(window.get('phases', {}).get(branch['id'], 0), 0, interval)
            travel = finite(branch.get('entry_travel', 0))
            t = start + phase
            while t < end:
                events.append({'line': branch['id'], 'entry_time': t, 'origin_departure': t-travel})
                if len(events) > 30000:
                    raise ValueError('预览超过 30000 班，请缩小时间范围')
                t += interval
    events.sort(key=lambda e: (e['entry_time'], e['line']))
    for i, e in enumerate(events):
        e['gap'] = e['entry_time']-events[i-1]['entry_time'] if i else None
    return {'events': events, 'segment': list(next(iter(common))),
            'scope': '共线入口目标序列；入口运行时间由用户确认，不自动修改游戏偏移组或保证车数充足。'}


def accounting(path: Path, kind='line', period='daily', metric='trains_signal_stop_time', timestamp=None) -> dict:
    metrics = {'trains_signal_stop_time', 'trains_late_arrival_time', 'pax_waited_too_long', 'pax_lost', 'train_departed_full', 'full_departure_ratio'}
    if metric not in metrics or kind not in {'line', 'station', 'train'}:
        raise ValueError('统计指标或对象类型无效')
    mark = fingerprint(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if not {'id', 'kind', 'period', 'timestamp'} <= set(reader.fieldnames or []):
            raise ValueError('不是受支持的游戏 Accounting TSV')
        rows = [r for r in reader if r['kind'] == kind and r['period'] == period]
    stamps = sorted({r['timestamp'] for r in rows})
    chosen = timestamp or (stamps[-1] if stamps else '')
    seen = set(); ranked = []
    for row in rows:
        if row['timestamp'] != chosen:
            continue
        if row['id'] in seen:
            raise ValueError('同一对象和统计周期出现重复记录，拒绝重复累计')
        seen.add(row['id'])
        def number(key):
            text = row.get(key)
            if text in (None, ''):
                return None
            value = float(text)
            return value if math.isfinite(value) else None
        if metric == 'full_departure_ratio':
            num, den = number('train_departed_full'), number('trains_departures')
            value = num / den if num is not None and den is not None and den > 0 else None
        else:
            value = number(metric)
        ranked.append({'id': row['id'], 'name': row.get('name') or row['id'], 'value': value})
    ranked.sort(key=lambda r: (r['value'] is None, -(r['value'] or 0), r['id']))
    if fingerprint(path) != mark:
        raise ValueError('会计文件正在更新，请重试')
    return {'rankings': ranked, 'timestamp': chosen, 'timestamps': stamps, 'metric': metric, 'source': str(path),
            'fingerprint': mark, 'kind': kind, 'period': period,
            'scope': '历史导出，单一对象粒度与周期。满载发车比例不是平均载客率；空值保持未知。'}


def parse_log(text: str) -> dict:
    records = []
    pending_timestamp = ''
    for line in text.splitlines():
        if 'NIMBY_DIAG|' not in line:
            # The in-game Development pane renders frame/time on a separate line.
            pending_timestamp = line.strip()[:300] if re.match(r'^\s*#[\d,]+\s*\|', line) else ''
            continue
        fields = line.split('NIMBY_DIAG|', 1)[1].split('|')
        prefix = line.split('NIMBY_DIAG|', 1)[0].strip()
        timestamp = pending_timestamp if re.fullmatch(r'L\d+', prefix) or not prefix else prefix
        records.append({'event': fields[0], 'timestamp': timestamp[:300], 'detail': '|'.join(fields[1:])[:1500]})
        pending_timestamp = ''
    return {'records': records[-2000:], 'total': len(records), 'counts': dict(Counter(r['event'] for r in records)),
            'scope': '仅显示采集到的事件；没有日志不代表没有调度问题。最多显示最近 2000 条。'}


def dispatch(request: dict, workers=1) -> dict:
    from toolkit_backend import emit_progress
    action = request['operation']
    emit_progress('workspace',2,100,'正在准备工作台检查；复杂存档可能需要几十秒…')
    path = Path(request.get('save') or '.')
    if action == 'catalog':
        cache_root = request.get('_cache_dir')
        mark = fingerprint(path)
        cache = Path(cache_root) / ('catalog-v2-' + mark + '.json') if cache_root else None
        if cache and cache.is_file():
            result = json.loads(cache.read_text('utf-8'))
            result.update(save=str(path), cache_hit=True)
        else:
            result = catalog(path)
            if cache:
                atomic_store(cache, result)
            result['cache_hit'] = False
    elif action == 'pair':
        result = pair_exports(path, request['exports'], workers)
    elif action == 'batch':
        result = batch(path, request)
        if result.get('preview'):
            result['preview_hash'] = hashlib.sha256(json.dumps(result['changes'], sort_keys=True).encode()).hexdigest()
    elif action == 'audit':
        from toolkit_backend import load_objects, validate_save_export
        mark, _, raw, _ = read_save(path)
        ep = Path(request['export']); em = fingerprint(ep); objects = load_objects(ep)
        validate_save_export(raw, objects)
        result = continuity(objects, request.get('depots'))
        if fingerprint(ep) != em or fingerprint(path) != mark:
            raise ValueError('文件已改变，请重新检查')
        result.update(fingerprint=mark, export_fingerprint=em)
    elif action == 'corridor':
        result = corridor(request['branches'], request['windows'])
    elif action == 'accounting':
        result = accounting(Path(request['accounting']), request.get('kind', 'line'), request.get('period', 'daily'), request.get('metric', 'trains_signal_stop_time'), request.get('timestamp'))
    else:
        raise ValueError('未知工作台操作')
    emit_progress('workspace',100,100,'工作台任务完成')
    return {'action': 'workspace', 'operation': action, **result}
