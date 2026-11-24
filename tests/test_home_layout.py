"""语音首页首屏放异常入口。三套预览不接真实提交。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = (ROOT / "zhiyu/static/index.html").read_text(encoding="utf-8")
DEBUG = (ROOT / "zhiyu/static/debug.html").read_text(encoding="utf-8")
PREVIEWS = (
    ROOT / "previews/home-workbench.html",
    ROOT / "previews/home-console.html",
    ROOT / "previews/home-editorial.html",
)


def test_voice_home_puts_incident_fields_on_the_first_band():
    css = (ROOT / "zhiyu/static/style.css").read_text(encoding="utf-8")
    assert 'class="phone home"' in HOME
    assert 'class="rail"' in HOME
    assert 'class="board"' in HOME
    assert HOME.index('id="scenario"') < HOME.index('id="status"')
    assert HOME.index('id="status"') < HOME.index('id="incident-panel"')
    assert ">异常情况提交<" in HOME
    assert "异常情况记录" not in HOME
    assert "静态演示" not in HOME
    assert 'id="incident-form"' in HOME
    assert 'id="incident-form" hidden' not in HOME
    assert 'id="incident-what"' in HOME
    assert 'id="incident-image"' in HOME
    assert 'id="call"' in HOME
    assert 'id="random"' in HOME
    assert 'id="echo"' in HOME
    assert 'id="open-debug"' in HOME
    assert "getUserMedia" not in HOME
    assert "京东 POP 商家资质审核比赛模拟客服" in HOME
    assert "不是京东官方服务" in HOME
    assert "body:has(main.home)" in css
    assert "#0c1413" in css
    assert "#3dbea5" in css
    assert "#0c1413" not in DEBUG


def test_debug_page_stays_a_text_tool():
    assert "debug-page" in DEBUG
    assert "phone home" not in DEBUG
    assert ">异常情况记录<" in DEBUG
    assert ">开始文字对话<" in DEBUG
    assert ">电话已结束<" in DEBUG
    assert "getUserMedia" not in DEBUG


def test_preview_pages_are_offline_static_demos():
    for path in PREVIEWS:
        text = path.read_text(encoding="utf-8")
        assert "智语外呼" in text
        assert "不是京东官方" in text
        assert "模拟" in text
        assert "http://" not in text
        assert "https://" not in text
        assert "getUserMedia" not in text
        assert "fetch(" not in text
        assert "<link" not in text
        assert "preventDefault" in text
