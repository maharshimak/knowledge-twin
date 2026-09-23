from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from knowledge_twin.graph import Edge, Entity, KnowledgeGraph


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
                    INSERT INTO edges(source, relation, target, evidence)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (edge.source, edge.relation, edge.target, edge.evidence)
                        for edge in graph.edges
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
                "SELECT source, relation, target, evidence FROM edges ORDER BY id"
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
            graph.add_edge(
                Edge(
                    source=row["source"],
                    relation=row["relation"],
                    target=row["target"],
                    evidence=row["evidence"],
                )
            )
        return graph
