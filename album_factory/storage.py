"""Private originals and public JPEG derivatives on the local data directory.

Originals are stored only as ``photos/{id}.original``. Callers that serve files
must use ``derivative`` (``jpg`` or ``thumb``); that path never points at an original.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DERIVATIVES = {"jpg": ".jpg", "thumb": ".thumb.jpg"}


def private_original(data_dir, photo_id) -> Path:
    return Path(data_dir) / "photos" / f"{photo_id}.original"


def derivative(data_dir, photo_id, variant) -> Path:
    suffix = _DERIVATIVES.get(variant)
    if suffix is None:
        raise ValueError("Публично доступны только варианты jpg и thumb")
    return Path(data_dir) / "photos" / f"{photo_id}{suffix}"


def purge_photo_files(data_dir, photo_id) -> None:
    private_original(data_dir, photo_id).unlink(missing_ok=True)
    derivative(data_dir, photo_id, "jpg").unlink(missing_ok=True)
    derivative(data_dir, photo_id, "thumb").unlink(missing_ok=True)


def _created(created_iso):
    moment = datetime.fromisoformat(created_iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def retention_deadline(created_iso, days=90) -> str:
    return (_created(created_iso) + timedelta(days=days)).date().isoformat()


def warn_days(created_iso):
    delete_on = retention_deadline(created_iso)
    remaining = (datetime.fromisoformat(delete_on).date() - datetime.now(timezone.utc).date()).days
    return {"delete_on": delete_on, "warn": remaining <= 14}
