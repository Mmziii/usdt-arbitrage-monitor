"""Page routes, bundled assets and the no-CDN rule for the new dashboard."""
import pathlib
import re

from app import main

STATIC = pathlib.Path(main.__file__).parent / 'static'
NEW_ASSETS = ['dashboard.html', 'ui.css', 'ui.js', 'sort.js', 'drawer.js', 'panels.js',
              'guide.html', 'Vazirmatn-Regular.woff2', 'OFL.txt']


def test_page_routes_exist():
    paths = {route.path for route in main.app.routes}
    assert {'/', '/overview', '/settings', '/classic', '/guide'} <= paths


def test_new_assets_are_bundled():
    for name in NEW_ASSETS:
        path = STATIC / name
        assert path.is_file(), name
        assert path.stat().st_size > 100, name


def test_dashboard_loads_its_scripts_in_order():
    html = (STATIC / 'dashboard.html').read_text(encoding='utf-8')
    order = [html.index('/static/' + name) for name in
             ['sort.js', 'ui.js', 'drawer.js', 'panels.js']]
    assert order == sorted(order)
    assert 'App.init()' in html and 'App.initPanels()' in html


def test_no_external_resources_in_the_new_ui():
    for name in ['dashboard.html', 'guide.html', 'ui.css', 'ui.js', 'sort.js',
                 'drawer.js', 'panels.js']:
        text = (STATIC / name).read_text(encoding='utf-8')
        text = text.replace('http://127.0.0.1:8000', '')      # documented local address
        assert 'http://' not in text, name
        assert 'https://' not in text, name
        assert '@import' not in text
        if name == 'ui.css':
            assert "url('/static/Vazirmatn-Regular.woff2')" in text, 'bundled font only'


def test_every_dom_id_used_by_the_scripts_exists_somewhere():
    html = (STATIC / 'dashboard.html').read_text(encoding='utf-8')
    present = set(re.findall(r'id="([^"]+)"', html))
    scripts = {name: (STATIC / name).read_text(encoding='utf-8')
               for name in ['ui.js', 'drawer.js', 'panels.js']}
    used = set()
    for source in scripts.values():
        used |= set(re.findall(r"\$\('([A-Za-z][A-Za-z0-9_-]*)'\)", source))
    # Panels render their own markup, so their ids live in the JS templates, not the shell.
    generated = ' '.join(scripts.values())
    missing = sorted(name for name in used - present
                     if f'id="{name}"' not in generated)
    assert not missing, f'no element is created for these ids: {missing}'


def test_persian_copy_is_used_on_the_new_pages():
    for name in ['dashboard.html', 'guide.html']:
        text = (STATIC / name).read_text(encoding='utf-8')
        assert 'dir="rtl"' in text and 'lang="fa"' in text
        persian = len(re.findall(r'[\u0600-\u06ff]', text))
        assert persian > 500, name
