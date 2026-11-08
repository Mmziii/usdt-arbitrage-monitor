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


def test_stylesheet_pins_the_hidden_attribute():
    """The X button bug came from .modal{display:flex} beating [hidden]; keep the guard."""
    css = (STATIC / 'ui.css').read_text(encoding='utf-8')
    assert re.search(r'\[\s*hidden\s*\]\s*\{[^}]*display\s*:\s*none\s*!important', css), \
        'ui.css needs a global [hidden] { display: none !important } rule'
    # A component rule that sets display must never be able to override it.
    for selector in ['.modal {', '.menu {', '.banner {', '.chip {']:
        assert selector in css
    assert css.index('[hidden]') < css.index('.modal {')


def test_theme_tokens_exist_without_javascript():
    css = (STATIC / 'ui.css').read_text(encoding='utf-8')
    root = css[css.index(':root {'):css.index('}', css.index(':root {'))]
    for token in ['--bg:', '--text:', '--surface:', '--border:']:
        assert token in root, token
    html = (STATIC / 'dashboard.html').read_text(encoding='utf-8')
    assert 'data-theme="system"' in html


def test_close_controls_exist_on_the_dashboard():
    html = (STATIC / 'dashboard.html').read_text(encoding='utf-8')
    for control in ['drawerClose', 'wizardClose', 'manualClose', 'setupBannerClose',
                    'messageClose']:
        assert 'id="' + control + '"' in html, control


def test_guide_page_is_static_and_linked():
    guide = (STATIC / 'guide.html').read_text(encoding='utf-8')
    assert '<script' not in guide
    assert 'data-theme="system"' in guide
    for href in ['href="/"', 'href="/settings"', 'href="/static/ui.css"']:
        assert href in guide, href
    dashboard = (STATIC / 'dashboard.html').read_text(encoding='utf-8')
    assert 'href="/guide"' in dashboard


NEW_HOME_ASSETS = ['home.html', 'home.css', 'home.js', 'fees.html', 'fees.js']


def test_the_home_screen_is_the_main_page():
    paths = {route.path for route in main.app.routes}
    assert {'/', '/fees', '/dashboard', '/guide', '/settings'} <= paths


def test_new_home_assets_are_bundled():
    for name in NEW_HOME_ASSETS:
        path = STATIC / name
        assert path.is_file(), name
        assert path.stat().st_size > 500, name


def test_the_home_page_starts_with_every_dialog_closed():
    html = (STATIC / 'home.html').read_text(encoding='utf-8')
    dialogs = re.findall(r'<dialog[^>]*>', html)
    assert dialogs, 'the page owns its dialogs'
    for tag in dialogs:
        assert ' open' not in tag, 'a dialog must never open on load: ' + tag
    fees = (STATIC / 'fees.html').read_text(encoding='utf-8')
    for tag in re.findall(r'<dialog[^>]*>', fees):
        assert ' open' not in tag


def test_the_home_page_is_persian_rtl_and_readable():
    html = (STATIC / 'home.html').read_text(encoding='utf-8')
    assert 'dir="rtl"' in html and 'lang="fa"' in html
    assert len(re.findall(r'[\u0600-\u06ff]', html)) > 500
    css = (STATIC / 'home.css').read_text(encoding='utf-8')
    assert re.search(r'html\s*\{\s*font-size:\s*1[6-9]px', css), 'base font must be >= 16px'
    assert 'prefers-color-scheme' in css and "data-theme='dark'" in css
    assert re.search(r'\[\s*hidden\s*\]\s*\{[^}]*display\s*:\s*none\s*!important', css)
    assert css.index('[hidden]') < css.index('.banner {')
    assert "url('/static/Vazirmatn-Regular.woff2')" in css


def test_home_and_fees_have_no_external_resources():
    for name in ['home.html', 'home.css', 'home.js', 'fees.html', 'fees.js']:
        text = (STATIC / name).read_text(encoding='utf-8')
        assert 'http://' not in text, name
        assert 'https://' not in text or name in ('fees.js', 'home.js'), name
        assert '@import' not in text, name
    # the fee pages link to the exchange's own page at runtime, never at build time
    assert 'https://' not in (STATIC / 'home.html').read_text(encoding='utf-8')


def test_every_id_used_by_the_home_scripts_exists():
    for html_name, script_name in [('home.html', 'home.js'), ('fees.html', 'fees.js')]:
        html = (STATIC / html_name).read_text(encoding='utf-8')
        script = (STATIC / script_name).read_text(encoding='utf-8')
        present = set(re.findall(r'id="([^"]+)"', html))
        used = set(re.findall(r"\$\('([A-Za-z][A-Za-z0-9_-]*)'\)", script))
        generated = set(re.findall(r"\.id = '([A-Za-z][A-Za-z0-9_-]*)'", script))
        missing = sorted(used - present - generated)
        assert not missing, f'{script_name} uses ids that do not exist: {missing}'


def test_navigation_points_at_every_area():
    html = (STATIC / 'home.html').read_text(encoding='utf-8')
    for href in ['href="/"', 'href="/fees"', 'href="/guide"', 'href="/settings"',
                 'href="/dashboard"']:
        assert href in html, href
    assert 'ابزارهای پیشرفته' in html
    fees = (STATIC / 'fees.html').read_text(encoding='utf-8')
    assert 'href="/fees"' in fees and 'aria-current="page"' in fees


def test_the_guide_explains_the_new_flow_and_the_risks():
    guide = (STATIC / 'guide.html').read_text(encoding='utf-8')
    assert '<script' not in guide
    for phrase in ['برو', 'صبر کن', 'نامطمئن', 'کارمزد', 'واژه‌نامه', 'ریسک']:
        assert phrase in guide, phrase
    assert 'href="/"' in guide and 'href="/settings"' in guide
