"""
`core.backup`: a dated zip of the state nothing else can rebuild.

The properties worth pinning down are the exclusions — credentials and
media stay out unless asked for — and that a live WAL-mode database is
captured consistently rather than as a half-written file copy.
"""

from __future__ import annotations

import sqlite3
import zipfile

import pytest

from core import backup
from core.errors import ConfigError


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "config" / "youtube_tokens").mkdir(parents=True)
    (root / "config" / "curricula").mkdir()
    (root / "config" / "channels.json").write_text("{}", encoding="utf-8")
    (root / "config" / "curricula" / "chan.json").write_text("{}", encoding="utf-8")
    (root / "config" / "youtube_client.json").write_text("secret", encoding="utf-8")
    (root / "config" / "youtube_tokens" / "chan.json").write_text("token", encoding="utf-8")
    (root / "channels" / "chan" / "logo").mkdir(parents=True)
    (root / "channels" / "chan" / "logo" / "logo.png").write_bytes(b"png")
    day = root / "output" / "chan" / "2026-09-23"
    day.mkdir(parents=True)
    (day / "clip.mp4").write_bytes(b"video")
    (day / "clip.mp3").write_bytes(b"audio")
    (day / "clip_publish.json").write_text("{}", encoding="utf-8")
    (day / "clip_meta.txt").write_text("script", encoding="utf-8")

    (root / "footage").mkdir()
    conn = sqlite3.connect(root / "footage" / "library.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE clips (filename TEXT)")
    conn.execute("INSERT INTO clips VALUES ('a.mp4')")
    conn.commit()
    # Left open, as the running web app would have it.
    yield root
    conn.close()


def _names(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        return set(archive.namelist())


def test_backs_up_state_and_leaves_out_secrets_and_media(project, tmp_path):
    zip_path = backup.create_backup(tmp_path / "dest", root=project)
    names = _names(zip_path)

    assert "config/channels.json" in names
    assert "config/curricula/chan.json" in names
    assert "channels/chan/logo/logo.png" in names
    assert "output/chan/2026-09-23/clip_publish.json" in names
    assert "output/chan/2026-09-23/clip_meta.txt" in names
    assert "footage/library.db" in names

    assert "config/youtube_client.json" not in names
    assert "config/youtube_tokens/chan.json" not in names
    assert not any(n.endswith((".mp4", ".mp3")) for n in names)


def test_include_secrets_adds_credentials(project, tmp_path):
    names = _names(backup.create_backup(tmp_path / "dest", root=project, include_secrets=True))
    assert "config/youtube_client.json" in names
    assert "config/youtube_tokens/chan.json" in names


def test_database_snapshot_is_readable_while_the_source_is_open(project, tmp_path):
    zip_path = backup.create_backup(tmp_path / "dest", root=project)
    extracted = tmp_path / "restored.db"
    with zipfile.ZipFile(zip_path) as archive:
        extracted.write_bytes(archive.read("footage/library.db"))
    conn = sqlite3.connect(extracted)
    try:
        assert conn.execute("SELECT filename FROM clips").fetchall() == [("a.mp4",)]
    finally:
        conn.close()


def test_prunes_to_the_newest_keep(project, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (dest / f"{backup.ARCHIVE_PREFIX}{stamp}.zip").write_bytes(b"old")

    newest = backup.create_backup(dest, root=project, keep=2)

    remaining = sorted(p.name for p in dest.glob("*.zip"))
    assert remaining == [f"{backup.ARCHIVE_PREFIX}20260103-000000.zip", newest.name]
    assert not list(dest.glob("*.partial"))


def test_refuses_a_destination_inside_the_project(project):
    with pytest.raises(ConfigError):
        backup.create_backup(project / "backups", root=project)
