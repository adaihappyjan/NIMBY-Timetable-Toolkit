from pathlib import Path

import toolkit_webapp as app


def test_autotrack_name_and_current_capabilities():
    root=Path(__file__).resolve().parents[1]
    html=(root/'web/index.html').read_text('utf-8')
    page=html.split('id="view-autotrack"',1)[1].split('<section class="view"',1)[0]
    assert '实验' not in page
    assert '自动铺轨 · 实验' not in html
    assert '实验' not in (root/'web/autotrack.js').read_text('utf-8')
    text=' '.join(row['name']+' '+row['detail'] for row in app.CAPABILITIES)
    for expected in ('沿途站','16384','预避让','车站名称','自动跟进','ORM','清理','免安装'):
        assert expected in text
    assert '实验功能' not in text
    assert '游戏内验收' in text and '不自动接站' in text


def test_release_notes_describe_boundaries_and_bundled_dependencies():
    root=Path(__file__).resolve().parents[1]
    notes=(root/'docs/RELEASE_1.8.6.txt').read_text('utf-8')
    for expected in ('1.8.6','Python','Node.js','新副本','未知高度','SHA-256'):
        assert expected in notes
