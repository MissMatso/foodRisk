"""Local, versioned artifact registry. Checksums detect changes, not malicious publishers."""

import hashlib
import json
import re
from pathlib import Path

from django.conf import settings
from .feature_contracts import get_contract

REGISTRY_ROOT = Path(__file__).parent / "models" / "registry"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def version_directory(version):
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", version):
        raise ValueError("Invalid model version")
    return Path(getattr(settings, "MODEL_REGISTRY_ROOT", REGISTRY_ROOT)) / version


def resolve_bundle(version=None, serving=True):
    version = version or settings.FOODRISK_MODEL_VERSION
    directory = version_directory(version)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = get_contract(manifest["feature_schema"])
    if manifest["model_version"] != version or manifest["features"] != contract.FEATURE_COLS:
        raise ValueError("Model/feature schema mismatch")
    artifact = directory / "model.joblib"
    if digest(artifact) != manifest["artifact_sha256"]:
        raise ValueError("Model checksum mismatch")
    if serving and not settings.DEBUG:
        approval = json.loads((directory / "approval.json").read_text(encoding="utf-8"))
        if (
            approval.get("scope") != "operational"
            or approval.get("manifest_sha256") != digest(manifest_path)
            or not manifest["validation"].get("ngo_external_validation")
        ):
            raise ValueError(
                "Operational use requires external validation and an approval bound to this manifest"
            )
    return artifact, manifest
