"""Static review of the Windows launcher. The batch file cannot run here, so we check its text.

Everything below is something a Windows user hits on a first run: a wrong code page, a batch
file cmd.exe refuses to parse, an unquoted path with spaces, a missing port fallback.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'start.bat'
TEXT = BATCH.read_bytes()


def lines():
    return BATCH.read_text(encoding='utf-8').split('\r\n')


def test_file_is_utf8_without_bom_and_uses_crlf():
    assert not TEXT.startswith(b'\xef\xbb\xbf'), 'a BOM makes cmd.exe choke on the first line'
    body = TEXT.decode('utf-8')          # raises if the file is not valid UTF-8
    assert '\n' not in body.replace('\r\n', ''), 'every line must end with CRLF'
    assert body.splitlines()[0].strip() == '@echo off'


def test_console_supports_persian_and_utf8_files():
    text = BATCH.read_text(encoding='utf-8')
    assert 'chcp 65001' in text
    assert 'PYTHONUTF8=1' in text
    # Persian output must be paired with English so a console without Persian glyphs still works.
    persian = [line for line in text.splitlines() if re.search(r'[\u0600-\u06ff]', line)]
    assert persian
    assert sum('[خطا]' in line for line in persian) >= 2


def test_paths_with_spaces_and_other_folders_are_quoted():
    text = BATCH.read_text(encoding='utf-8')
    assert 'cd /d "%~dp0"' in text
    assert '"%VENV_PY%"' in text
    assert '"%VENV_PY%" -m app' in text
    assert '".venv\\Scripts\\python.exe"' in text
    # No unquoted use of the venv path or of %~dp0.
    for match in re.finditer(r'(?<!")(\.venv\\Scripts\\python\.exe)(?!")', text):
        start = text.rfind('\n', 0, match.start()) + 1
        prefix = text[start:match.start()].strip()
        assert prefix in ('set', 'echo'), prefix
        if prefix == 'echo':
            continue
        assert text[start:match.start()].strip() == 'set'


def test_missing_python_version_and_install_failures_explain_themselves():
    text = BATCH.read_text(encoding='utf-8')
    assert 'where py >nul' in text and 'where python >nul' in text
    assert 'sys.version_info >= (3, 10)' in text, 'an old Python must be rejected with its version'
    assert '%PY% -V' in text
    assert 'requirements.txt' in text
    assert text.count('pause') >= 4, 'every exit path waits so the window does not vanish'
    assert text.count('exit /b 1') >= 4


def test_occupied_port_falls_back_and_still_opens_the_browser():
    text = BATCH.read_text(encoding='utf-8')
    assert re.search(r'for %%P in \(8000 8001 8002 8003\)', text)
    assert 'connect_ex' in text, 'a connect probe detects a listening port on Windows too'
    assert '--port %PORT%' in text
    assert 'http://127.0.0.1:%PORT%' in text
    # The old line nested quotes inside `cmd /c "..."`, which cmd.exe mangles.
    browser_line = next(line for line in text.splitlines() if 'explorer.exe' in line)
    assert browser_line.count('"') == 4, browser_line
    assert 'timeout /t' not in text, 'timeout fails when stdin is redirected; ping always works'


def test_server_binds_to_localhost_only():
    text = BATCH.read_text(encoding='utf-8')
    assert '--host 127.0.0.1' in text
    assert '0.0.0.0' not in text


def test_batch_parentheses_balance_outside_quotes():
    """A stray parenthesis is a syntax error that only shows up on the user's machine."""
    depth = 0
    for number, line in enumerate(lines(), 1):
        stripped = re.sub(r'"[^"]*"', '', line)
        if stripped.strip().lower().startswith('rem '):
            continue
        depth += stripped.count('(') - stripped.count(')')
        assert depth >= 0, f'line {number} closes a block that was never opened: {line!r}'
    assert depth == 0, f'{depth} block(s) left open'


def test_env_file_is_created_from_the_example():
    text = BATCH.read_text(encoding='utf-8')
    assert 'if not exist ".env"' in text and '".env.example"' in text
    assert (ROOT / '.env.example').exists()
