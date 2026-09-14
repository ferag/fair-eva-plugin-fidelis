from __future__ import annotations

import subprocess

import pytest

import fidelis


def test_check_reports_missing_docker(monkeypatch, capsys):
    monkeypatch.setattr(fidelis.shutil, "which", lambda _command: None)

    with pytest.raises(SystemExit, match="1"):
        fidelis.check_prerequisites()

    assert "Docker no está instalado" in capsys.readouterr().err


def test_check_accepts_working_docker(monkeypatch, capsys):
    monkeypatch.setattr(fidelis.shutil, "which", lambda _command: "/usr/bin/docker")
    monkeypatch.setattr(
        fidelis,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode=0),
    )

    fidelis.check_prerequisites()

    assert "Docker y Compose están disponibles" in capsys.readouterr().out


def test_check_reports_unavailable_compose(monkeypatch, capsys):
    monkeypatch.setattr(fidelis.shutil, "which", lambda _command: "/usr/bin/docker")
    monkeypatch.setattr(
        fidelis,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode=1),
    )

    with pytest.raises(SystemExit, match="1"):
        fidelis.check_prerequisites()

    assert "Compose v2 no está disponible" in capsys.readouterr().err
