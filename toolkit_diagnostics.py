"""Read-only train probe. No dispatch, warping or occupation overrides."""
from pathlib import Path
import uuid
import hashlib
import json
import re
import zipfile

SOURCE = '''script meta {
    lang: nimbyscript.v1,
    api: nimbyrails.v1,
}
pub struct ToolkitDiagnostic extend Train {
    meta { label: "Toolkit read-only diagnostic", },
}
struct ToolkitProbeState {
    state: i64,
    ticks: i64,
}
pub fn ToolkitDiagnostic::control_train(
    self: &ToolkitDiagnostic,
    ctx: &EventCtx,
    train: &Train,
    motion: &Motion,
    sc: &mut SimController
) {
    let state: mut i64 = 0;
    if is_valid(motion.schedule_dispatch.get()) { state = 1; }
    if is_valid(motion.timed_stop.get()) { state = 2; }
    if let drive &= motion.drive.get() {
        if is_valid(ctx.db.view(drive.waiting_signal_id)) { state = 3; }
    }
    let ticks: mut i64 = 10;
    if let prior &= ctx.db.view<ToolkitProbeState>(train) {
        ticks = prior.ticks + 1;
        if ticks < 10 {
            let pending &mut= prior.clone();
            pending.ticks = ticks;
            sc.queue_attach(train, pending);
            return;
        }
        if prior.state == state && ticks < 50 {
            let pending &mut= prior.clone();
            pending.ticks = ticks;
            sc.queue_attach(train, pending);
            return;
        }
    }
    if state == 0 { log("NIMBY_DIAG|UNASSIGNED|@", train.id); }
    if state == 1 { log("NIMBY_DIAG|ASSIGNED|@", train.id); }
    if state == 2 { log("NIMBY_DIAG|TIMED_STOP|@", train.id); }
    if state == 3 {
        if let drive &= motion.drive.get() {
            log("NIMBY_DIAG|SIGNAL_WAIT|@|@", train.id, drive.waiting_signal_id);
        }
    }
    let next &mut= ToolkitProbeState::new();
    next.state = state;
    next.ticks = 0;
    sc.queue_attach(train, next);
}
'''

MOD = '''[ModMeta]
schema=1
name=Toolkit read-only diagnostic (preview)
author=NIMBY Timetable Toolkit
desc=Opt-in train state logger; no dispatch changes. Enable debug logging manually.
version=1.0.0
signature=0

[Script]
id=toolkit_readonly_diagnostic
name=Toolkit read-only diagnostic
source=Diagnostics.nimbyscript
'''


def install_diagnostic(save_dir: Path) -> dict:
    from toolkit_scriptgen import validate_script_source
    validation = validate_script_source(SOURCE)
    if not validation['valid']:
        raise ValueError('诊断源码未通过静态检查')
    root = save_dir.resolve() / 'mods'
    if root.resolve().parent != save_dir.resolve():
        raise ValueError('mods 目录指向存档目录之外，拒绝安装')
    root.mkdir(exist_ok=True)
    target = root / 'toolkit_readonly_diagnostic'
    if target.exists():
        if (target / 'Diagnostics.nimbyscript').read_text('utf-8') == SOURCE and (target / 'mod.txt').read_text('utf-8') == MOD:
            return {'path': str(target), 'already_installed': True, 'enabled': 'unknown'}
        raise ValueError('已有不同版本的同名模组；为保留用户修改，不自动覆盖')
    staging = root / ('.toolkit-install-' + uuid.uuid4().hex)
    staging.mkdir()
    # Only application-owned constant files are installed; no arbitrary ZIP paths.
    (staging / 'Diagnostics.nimbyscript').write_text(SOURCE, encoding='utf-8')
    (staging / 'mod.txt').write_text(MOD, encoding='utf-8')
    staging.rename(target)
    return {'path': str(target), 'already_installed': False, 'enabled': 'unknown'}


def record_generated_archive(path: Path) -> None:
    from toolkit_workspace import atomic_store
    atomic_store(path.with_suffix('.generated.json'), {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})


def install_generated_archive(archive_path: Path, save_dir: Path) -> dict:
    """Only current, hash-receipted toolkit output; no arbitrary ZIP installation."""
    receipt=archive_path.with_suffix('.generated.json')
    if not receipt.is_file() or hashlib.sha256(archive_path.read_bytes()).hexdigest()!=json.loads(receipt.read_text('utf-8')).get('sha256'):
        raise ValueError('不是本工具生成的原始模组包，或文件已被修改；请重新生成。')
    root=save_dir.resolve()/'mods'
    if root.resolve().parent!=save_dir.resolve():
        raise ValueError('mods 目录指向存档目录之外，拒绝安装')
    with zipfile.ZipFile(archive_path) as archive:
        infos=archive.infolist()
        if not infos or len(infos)>2000 or sum(i.file_size for i in infos)>100*1024*1024:
            raise ValueError('模组包超出安全大小限制')
        names=[i.filename for i in infos]
        if len(names)!=len(set(n.casefold() for n in names)):
            raise ValueError('模组包含重复文件名')
        folders=set()
        for i in infos:
            parts=i.filename.rstrip('/').split('/')
            if len(parts)<2 or any(p in ('','.','..') or re.search(r'[\\:<>"]',p) or p.endswith(('.', ' ')) for p in parts) or (i.external_attr>>16)&0o170000==0o120000:
                raise ValueError('模组包包含不安全路径或链接')
            folders.add(parts[0])
        if len(folders)!=1:
            raise ValueError('模组包必须只有一个顶层目录')
        folder=next(iter(folders))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',folder) or f'{folder}/mod.txt' not in names:
            raise ValueError('模组标识或 mod.txt 无效')
        target=root/folder
        if target.exists():
            raise ValueError('此模组目录已经存在；不覆盖用户文件。可更换生成包的 ID。')
        root.mkdir(exist_ok=True)
        staging=root/('.toolkit-install-'+uuid.uuid4().hex)
        staging.mkdir()
        try:
            for i in infos:
                relative=Path(*i.filename.split('/')[1:])
                out=staging/relative
                if staging.resolve() not in out.resolve().parents:
                    raise ValueError('安装路径越界')
                if i.is_dir():
                    out.mkdir(parents=True,exist_ok=True)
                else:
                    out.parent.mkdir(parents=True,exist_ok=True)
                    with out.open('xb') as stream:
                        stream.write(archive.read(i))
            staging.rename(target)
        finally:
            if staging.exists() and staging.resolve().parent==root.resolve() and staging.name.startswith('.toolkit-install-'):
                import shutil
                shutil.rmtree(staging)
    return {'path':str(target),'enabled':'unknown','note':'已安装文件；仍需在游戏内启用模组及对应对象扩展。'}
