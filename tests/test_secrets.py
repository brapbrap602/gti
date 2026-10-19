import pytest

from copy_legacy import copy_legacy
from secret_scan import SecretsFound, scan_text

# Built at runtime so this file never matches the repo-wide scan.
GOOGLE_KEY = "AIza" + "Sy" + "A" * 33
OPENROUTER_KEY = "sk-or-" + "v1-" + "0123456789abcdef" * 4


@pytest.mark.parametrize(
    ("kind", "key"), [("google", GOOGLE_KEY), ("openrouter", OPENROUTER_KEY)], ids=["google", "openrouter"]
)
def test_secrets_scan_copy_aborts_and_names_file(tmp_path, kind, key):
    clean, dirty = tmp_path / "src" / "Clean Novel", tmp_path / "src" / "Dirty Novel"
    clean.mkdir(parents=True)
    dirty.mkdir()
    (clean / "main.py").write_text("print('ok')\n")
    (dirty / "main.py").write_text("x = 1\n")
    (dirty / "translator.py").write_text(f'genai.configure(api_key=r"{key}")\n')
    dest = tmp_path / "legacy"

    with pytest.raises(SecretsFound) as exc:
        copy_legacy([clean, dirty], dest)

    [finding] = exc.value.findings
    assert (finding.path.name, finding.line, finding.kind) == ("translator.py", 1, kind)
    assert "translator.py" in str(exc.value) and key not in str(exc.value)
    assert not dest.exists()  # nothing copied, not even the clean folder


def test_copy_writes_slugged_folders_of_top_level_py(tmp_path):
    src = tmp_path / "The Death Mage Who Doesn't Want A Fourth Time"
    (src / "sub").mkdir(parents=True)
    (src / "main.py").write_text("print('ok')\n")
    (src / "notes.txt").write_text("not code\n")
    (src / "sub" / "deep.py").write_text("print('deep')\n")

    [dest] = copy_legacy([src], tmp_path / "legacy")

    assert dest.name == "the-death-mage-who-doesn-t-want-a-fourth-time"
    assert sorted(p.name for p in dest.iterdir()) == ["main.py"]


def test_copy_refuses_existing_destination(tmp_path):
    src = tmp_path / "ccg"
    src.mkdir()
    (tmp_path / "legacy" / "ccg").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        copy_legacy([src], tmp_path / "legacy")


def test_scan_ignores_prose_mentions_of_key_prefixes():
    assert scan_text("a `AIza…` / `sk-or-…` shaped string", path=None) == []
