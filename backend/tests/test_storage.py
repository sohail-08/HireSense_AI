import pytest

from app import storage


def test_private_storage_path_stays_inside_root(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "storage_root", lambda: tmp_path)

    assert storage.private_storage_path("cvs/candidate.pdf") == (
        tmp_path / "cvs" / "candidate.pdf"
    )


def test_private_storage_path_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "storage_root", lambda: tmp_path)

    with pytest.raises(ValueError):
        storage.private_storage_path("../outside.pdf")


def test_ensure_cv_storage_root_creates_private_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "storage_root", lambda: tmp_path)

    result = storage.ensure_cv_storage_root()

    assert result == tmp_path / "cvs"
    assert result.is_dir()


def test_ensure_knowledge_storage_root_creates_private_directory(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(storage, "storage_root", lambda: tmp_path)

    result = storage.ensure_knowledge_storage_root()

    assert result == tmp_path / "knowledge"
    assert result.is_dir()
