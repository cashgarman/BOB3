from __future__ import annotations

from pathlib import Path


class MemoryGraph:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db = None
        self._conn = None

    def load(self) -> None:
        import kuzu

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self.path))
        self._conn = kuzu.Connection(self._db)
        self._conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Entity(name STRING, typ STRING, PRIMARY KEY(name))"
        )
        self._conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Fact(id STRING, PRIMARY KEY(id))"
        )
        self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Fact TO Entity)"
        )
        self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS RELATED(FROM Entity TO Entity, rel STRING, fact_id STRING)"
        )
        self._upsert_entity("user", "person")

    def _upsert_entity(self, name: str, typ: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        typ = (typ or "thing").strip() or "thing"
        try:
            self._conn.execute(
                "MERGE (e:Entity {name: $name}) ON CREATE SET e.typ = $typ",
                {"name": name, "typ": typ},
            )
        except Exception:
            try:
                self._conn.execute(
                    "CREATE (e:Entity {name: $name, typ: $typ})",
                    {"name": name, "typ": typ},
                )
            except Exception:
                pass

    def attach_fact(
        self,
        fact_id: str,
        entities: list[dict[str, str]],
        relations: list[dict[str, str]],
    ) -> None:
        try:
            self._conn.execute("MERGE (f:Fact {id: $id})", {"id": fact_id})
        except Exception:
            try:
                self._conn.execute("CREATE (f:Fact {id: $id})", {"id": fact_id})
            except Exception:
                pass
        for ent in entities:
            name = (ent.get("name") or "").strip()
            if not name:
                continue
            self._upsert_entity(name, ent.get("type") or "thing")
            try:
                self._conn.execute(
                    "MATCH (f:Fact {id: $fid}), (e:Entity {name: $name}) "
                    "MERGE (f)-[:MENTIONS]->(e)",
                    {"fid": fact_id, "name": name},
                )
            except Exception:
                pass
        for rel in relations:
            src = (rel.get("src") or "user").strip() or "user"
            dst = (rel.get("dst") or "").strip()
            kind = (rel.get("rel") or "related").strip() or "related"
            if not dst:
                continue
            self._upsert_entity(src, "person" if src == "user" else "thing")
            self._upsert_entity(dst, "thing")
            try:
                self._conn.execute(
                    "MATCH (a:Entity {name: $src}), (b:Entity {name: $dst}) "
                    "CREATE (a)-[:RELATED {rel: $rel, fact_id: $fid}]->(b)",
                    {"src": src, "dst": dst, "rel": kind, "fid": fact_id},
                )
            except Exception:
                pass

    def related_fact_ids(self, names: list[str]) -> list[str]:
        ids: set[str] = set()
        for name in names:
            name = name.strip()
            if not name:
                continue
            try:
                result = self._conn.execute(
                    "MATCH (e:Entity {name: $name})<-[:MENTIONS]-(f:Fact) RETURN f.id",
                    {"name": name},
                )
                ids.update(self._col(result))
            except Exception:
                pass
            try:
                result = self._conn.execute(
                    "MATCH (e:Entity {name: $name})-[r:RELATED]-(:Entity) RETURN r.fact_id",
                    {"name": name},
                )
                ids.update(self._col(result))
            except Exception:
                pass
        return [i for i in ids if i]

    def remove_fact(self, fact_id: str) -> None:
        try:
            self._conn.execute("MATCH (f:Fact {id: $id}) DETACH DELETE f", {"id": fact_id})
        except Exception:
            pass

    def clear(self) -> None:
        try:
            self._conn.execute("MATCH (f:Fact) DETACH DELETE f")
            self._conn.execute("MATCH (e:Entity) WHERE e.name <> 'user' DETACH DELETE e")
        except Exception:
            pass

    def _col(self, result) -> list[str]:
        out = []
        try:
            while result.has_next():
                row = result.get_next()
                if row:
                    out.append(str(row[0]))
        except Exception:
            pass
        return out
