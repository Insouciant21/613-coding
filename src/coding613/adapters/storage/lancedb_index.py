"""Rebuildable LanceDB index containing vectors and authoritative-memory IDs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import lancedb  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
from pydantic import Field, field_validator

from coding613.domain.models import MemoryType
from coding613.domain.models_base import DomainModel


class VectorEntry(DomainModel):
    memory_id: UUID
    project_id: UUID
    memory_type: MemoryType
    permission_tags: frozenset[str] = Field(default_factory=frozenset)
    vector: tuple[float, ...] = Field(min_length=1)

    @field_validator("permission_tags")
    @classmethod
    def validate_permission_tags(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not tag or not tag.replace("-", "").replace("_", "").isalnum() for tag in value):
            raise ValueError("permission tags must be alphanumeric identifiers")
        return value


class MemoryQuery(DomainModel):
    project_id: UUID
    memory_types: frozenset[MemoryType] = Field(default_factory=frozenset)
    allowed_permission_tags: frozenset[str] = Field(default_factory=frozenset)


class VectorHit(DomainModel):
    memory_id: UUID
    distance: float = Field(ge=0)


class LanceMemoryIndex:
    _TABLE_NAME = "memory_vectors"

    def __init__(self, path: str | Path, dimension: int) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self._database = lancedb.connect(Path(path))
        if self._TABLE_NAME not in self._database.list_tables().tables:
            schema = pa.schema(
                [
                    pa.field("memory_id", pa.string()),
                    pa.field("project_id", pa.string()),
                    pa.field("memory_type", pa.string()),
                    pa.field("permission_tags", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), dimension)),
                ]
            )
            self._database.create_table(self._TABLE_NAME, schema=schema)
        self._table = self._database.open_table(self._TABLE_NAME)

    def upsert(self, entries: tuple[VectorEntry, ...]) -> None:
        if not entries:
            return
        if any(len(entry.vector) != self.dimension for entry in entries):
            raise ValueError("vector dimension mismatch")
        identifiers = ", ".join(f"'{entry.memory_id}'" for entry in entries)
        self._table.delete(f"memory_id IN ({identifiers})")
        self._table.add(
            [
                {
                    "memory_id": str(entry.memory_id),
                    "project_id": str(entry.project_id),
                    "memory_type": entry.memory_type.value,
                    "permission_tags": self._permission_scope(entry.permission_tags),
                    "vector": list(entry.vector),
                }
                for entry in entries
            ]
        )

    def query(
        self, vector: tuple[float, ...], filters: MemoryQuery, limit: int
    ) -> list[VectorHit]:
        if len(vector) != self.dimension:
            raise ValueError("vector dimension mismatch")
        if limit < 1:
            raise ValueError("limit must be positive")
        clauses = [f"project_id = '{filters.project_id}'"]
        if filters.memory_types:
            values = ", ".join(f"'{memory_type.value}'" for memory_type in filters.memory_types)
            clauses.append(f"memory_type IN ({values})")
        if filters.allowed_permission_tags:
            permission_clauses = ["permission_tags = ''"] + [
                f"permission_tags LIKE '%|{tag}|%'" for tag in filters.allowed_permission_tags
            ]
            clauses.append(f"({' OR '.join(permission_clauses)})")
        else:
            clauses.append("permission_tags = ''")
        rows = (
            self._table.search(list(vector))
            .where(" AND ".join(clauses))
            .limit(limit)
            .to_list()
        )
        return [
            VectorHit(memory_id=UUID(row["memory_id"]), distance=float(row["_distance"]))
            for row in rows
        ]

    def delete_project(self, project_id: UUID) -> None:
        self._table.delete(f"project_id = '{project_id}'")

    @staticmethod
    def _permission_scope(tags: frozenset[str]) -> str:
        return "" if not tags else "|" + "|".join(sorted(tags)) + "|"
