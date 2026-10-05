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
