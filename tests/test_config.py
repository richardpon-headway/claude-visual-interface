"""The YAML-backed daemon settings: default working dir, override, and the
graceful fallbacks when the file is missing, malformed, or points somewhere bad."""

from daemon import config


def test_working_dir_defaults_to_repo_parent_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_CONFIG_PATH", str(tmp_path / "absent.yaml"))
    assert config.get_working_dir() == config.REPO_PARENT


def test_working_dir_reads_configured_value(tmp_path, monkeypatch):
    workdir = tmp_path / "code"
    workdir.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"working_dir: {workdir}\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    assert config.get_working_dir() == workdir


def test_working_dir_expands_user(tmp_path, monkeypatch):
    # A leading ~ is expanded against HOME. Quoted so YAML reads it as a string
    # (a bare ~ is YAML's null).
    (tmp_path / "code").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text('working_dir: "~/code"\n')
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    assert config.get_working_dir() == tmp_path / "code"


def test_working_dir_falls_back_when_not_a_directory(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"working_dir: {tmp_path / 'does-not-exist'}\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    assert config.get_working_dir() == config.REPO_PARENT


def test_working_dir_falls_back_on_blank_value(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("working_dir:\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    assert config.get_working_dir() == config.REPO_PARENT


def test_working_dir_falls_back_on_malformed_yaml(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("working_dir: [unterminated\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    assert config.get_working_dir() == config.REPO_PARENT


def test_working_dir_falls_back_when_not_a_mapping(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("- just\n- a\n- list\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    assert config.get_working_dir() == config.REPO_PARENT


def test_ensure_config_file_seeds_default(tmp_path, monkeypatch):
    cfg = tmp_path / "nested" / "config.yaml"
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    config.ensure_config_file()
    assert cfg.exists()
    assert str(config.REPO_PARENT) in cfg.read_text()


def test_ensure_config_file_never_overwrites(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("working_dir: /custom/path\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))
    config.ensure_config_file()
    assert cfg.read_text() == "working_dir: /custom/path\n"
