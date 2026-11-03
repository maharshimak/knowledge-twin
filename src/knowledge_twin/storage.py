from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from knowledge_twin.graph import Edge, Entity, EvidenceSpan, KnowledgeGraph

# Columns added after the original schema; existing databases are migrated in
# place with ALTER TABLE so previously saved graphs keep loading.
_EDGE_MIGRATIONS = {
    "origin": "ALTER TABLE edges ADD COLUMN origin TEXT NOT NULL DEFAULT 'unspecified'",
    "provenance": "ALTER TABLE edges ADD COLUMN provenance TEXT",
    "retracted": "ALTER TABLE edges ADD COLUMN retracted INTEGER NOT NULL DEFAULT 0",
}


class SQLiteGraphStore:
    """Durable local graph storage with evidence-preserving round trips."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(Path(path))
        Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    FOREIGN KEY(source) REFERENCES entities(id),
                    FOREIGN KEY(target) REFERENCES entities(id)
                );
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(edges)")}
            for column, statement in _EDGE_MIGRATIONS.items():
                if column not in columns:
                    connection.execute(statement)
            connection.commit()

    def save(self, graph: KnowledgeGraph) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                connection.execute("DELETE FROM edges")
                connection.execute("DELETE FROM entities")
                connection.executemany(
                    """
                    INSERT INTO entities(id, kind, name, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (entity.id, entity.kind, entity.name, entity.description)
                        for entity in graph.entities.values()
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO edges(
                        source, relation, target, evidence, origin, provenance, retracted
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            edge.source,
                            edge.relation,
                            edge.target,
                            edge.evidence,
                            edge.origin,
                            _provenance_json(edge),
                            retracted,
                        )
                        for retracted, edges in ((0, graph.edges), (1, graph.retracted_edges))
                        for edge in edges
                    ],
                )

    def load(self) -> KnowledgeGraph:
        graph = KnowledgeGraph()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            entities = connection.execute(
                "SELECT id, kind, name, description FROM entities ORDER BY id"
            ).fetchall()
            edges = connection.execute(
                "SELECT source, relation, target, evidence, origin, provenance, retracted "
                "FROM edges ORDER BY id"
            ).fetchall()

        for row in entities:
            graph.add_entity(
                Entity(
                    id=row["id"],
                    kind=row["kind"],
                    name=row["name"],
                    description=row["description"],
                )
            )
        for row in edges:
            edge = Edge(
                source=row["source"],
                relation=row["relation"],
                target=row["target"],
                evidence=row["evidence"],
                origin=row["origin"],
                provenance=(
                    EvidenceSpan.from_dict(json.loads(row["provenance"]))
                    if row["provenance"] is not None
                    else None
                ),
            )
            if row["retracted"]:
                graph.retracted_edges.append(edge)
            else:
                graph.add_edge(edge)
        return graph


def _provenance_json(edge: Edge) -> str | None:
    if edge.provenance is None:
        return None
    return json.dumps(edge.provenance.to_dict(), sort_keys=True, ensure_ascii=False)
