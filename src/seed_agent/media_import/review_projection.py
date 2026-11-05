"""Exact source and destination authority for a fenced media review."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from seed_agent.media_import import filesystem as fs

KEY = "_publication_projection"


class ReviewProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    generation: int = Field(ge=1)
    target: str
    source_root_identity: str
    target_root_identity: str
    epoch: str
    config_revision: str
    source_status: str
    source_readiness: str | None
    plan_revision: int = Field(ge=0)
    decision_revision: int = Field(ge=0)

    def validate_source(self, engine, profile, source):
        if (
            source["path"] != self.path
            or source["generation"] != self.generation
            or engine.store_epoch != self.epoch
            or engine.configuration_revision() != self.config_revision
            or fs.root_health(Path(profile.source_root), profile.marker, profile.marker_value)
            != self.source_root_identity
        ):
            raise ValueError("review projection source or configuration changed")

    def validate_receipt(self, receipt, fingerprint):
        if [receipt.get(key) for key in ("dev", "ino", "size", "mtime_ns")] != json.loads(
            fingerprint
        ):
            raise ValueError("publication receipt differs from reviewed source fingerprint")

    def validate_destination(self, target, descriptor):
        if str(target) != self.target or descriptor["identity"] != self.target_root_identity:
            raise ValueError("review projection destination changed")

    def validate_target(self, conn, source_id, target, descriptor):
        self.validate_destination(target, descriptor)
        if target.exists() or target.is_symlink():
            raise ValueError("review projection target already occupied")
        self.validate_claims(conn, source_id)

    def validate_claims(self, conn, source_id, *, own_artifact=None):
        if (
            conn.execute(
                "SELECT 1 FROM media_import_jobs WHERE target=? AND source_id!=? LIMIT 1",
                (self.target, source_id),
            ).fetchone()
            or conn.execute(
                "SELECT 1 FROM media_artifacts WHERE path=? AND id IS NOT ? "
                "AND status IN ('active','publishing','deleting') LIMIT 1",
                (self.target, own_artifact),
            ).fetchone()
        ):
            raise ValueError("review projection target already claimed")


def from_decision(decision):
    value = json.loads(decision["mapping_json"]).get(KEY) if decision else None
    return ReviewProjection.model_validate(value) if value is not None else None
