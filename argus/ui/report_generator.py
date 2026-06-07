from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from argus.services.knowledge_graph.schema import init_db
from argus.shared.config import settings


class MarkdownReportGenerator:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.sqlite_path

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self._db_path)

    def generate(self, task_id: str, cost_report: dict[str, Any] | None = None) -> str:
        conn = self._get_db()
        lines: list[str] = []

        lines.append(f"# Research Report: {task_id}")
        lines.append("")

        entities = conn.execute(
            "SELECT id, name, type, description, confidence, attributes "
            "FROM entities WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        if entities:
            lines.append("## Entities Found")
            lines.append("")
            lines.append("| Name | Type | Confidence |")
            lines.append("|------|------|------------|")
            for entity in entities:
                name = entity[1]
                etype = entity[2]
                conf = f"{entity[4]:.0%}"
                lines.append(f"| {name} | {etype} | {conf} |")
            lines.append("")

        claims = conn.execute(
            """SELECT c.statement, c.confidence, c.source_urls, e.name
               FROM claims c
               LEFT JOIN entities e ON c.entity_id = e.id
               WHERE c.task_id = ?
               ORDER BY c.confidence DESC""",
            (task_id,),
        ).fetchall()
        if claims:
            lines.append("## Claims Extracted")
            lines.append("")
            for i, claim in enumerate(claims, start=1):
                statement, confidence, source_urls_raw, entity_name = claim
                lines.append(f"### {i}. {statement}")
                lines.append("")
                lines.append(f"- **Confidence**: {confidence:.0%}")
                if entity_name:
                    lines.append(f"- **Entity**: {entity_name}")

                urls: list[str] = []
                if isinstance(source_urls_raw, str):
                    try:
                        urls = json.loads(source_urls_raw)
                    except (json.JSONDecodeError, TypeError):
                        urls = []
                if urls:
                    lines.append("- **Sources**:")
                    for url in urls:
                        lines.append(f"  - [{url}]({url})")
                lines.append("")

        sources = conn.execute(
            "SELECT url, title, credibility_score FROM sources WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        if sources:
            lines.append("## Sources Referenced")
            lines.append("")
            for i, source in enumerate(sources, start=1):
                url, title, credibility = source
                title_text = title or url
                lines.append(f"{i}. [{title_text}]({url}) — credibility: {credibility:.0%}")
            lines.append("")

        if cost_report:
            lines.append("## Cost Breakdown")
            lines.append("")
            lines.append(f"- **Total Cost**: ${cost_report.get('total_cost', 0.0):.4f}")
            budget = cost_report.get("budget_limit", settings.budget_per_research)
            lines.append(f"- **Budget Limit**: ${budget:.4f}")
            breakdown: dict[str, float] = cost_report.get("breakdown", {})
            if breakdown:
                lines.append("- **By Category**:")
                for category, amount in sorted(breakdown.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"  - {category}: ${amount:.4f}")
            lines.append("")

        conn.close()
        return "\n".join(lines)


class HTMLReportGenerator:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.sqlite_path
        templates_dir = Path(__file__).parent / "templates"
        self._env = Environment(loader=FileSystemLoader(str(templates_dir)))

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self._db_path)

    def generate(self, task_id: str, cost_report: dict[str, Any] | None = None) -> str:
        conn = self._get_db()

        entities = conn.execute(
            "SELECT id, name, type, description, confidence FROM entities WHERE task_id = ?",
            (task_id,),
        ).fetchall()

        claim_rows = conn.execute(
            """
               SELECT c.id, c.statement, c.confidence, c.source_urls,
                      c.attribute, e.name AS entity_name
               FROM claims c
               LEFT JOIN entities e ON c.entity_id = e.id
               WHERE c.task_id = ?
               ORDER BY c.confidence DESC
            """,
            (task_id,),
        ).fetchall()

        source_rows = conn.execute(
            "SELECT url, title, credibility_score FROM sources WHERE task_id = ?",
            (task_id,),
        ).fetchall()

        edges = conn.execute(
            "SELECT source_id, target_id, relation_type, weight FROM edges WHERE task_id = ?",
            (task_id,),
        ).fetchall()

        conn.close()

        claims_data: list[dict[str, Any]] = []
        for c in claim_rows:
            urls_raw: Any = c[3]
            urls: list[str] = []
            if isinstance(urls_raw, str):
                try:
                    urls = json.loads(urls_raw)
                except (json.JSONDecodeError, TypeError):
                    urls = []
            elif isinstance(urls_raw, (list, tuple)):
                urls = list(urls_raw)
            sources_for_claim = [
                {"url": s[0], "title": s[1], "credibility": s[2]}
                for s in source_rows if s[0] in urls
            ]
            claims_data.append({
                "id": c[0],
                "statement": c[1],
                "confidence": c[2],
                "source_urls": urls,
                "attribute": c[4],
                "entity_name": c[5],
                "sources": sources_for_claim or [
                    {"url": u, "title": u, "credibility": 0.5}
                    for u in urls
                ],
            })

        node_map: dict[int, dict[str, Any]] = {}
        graph_nodes: list[dict[str, Any]] = []
        for e in entities:
            node = {
                "id": f"entity-{e[0]}",
                "name": e[1],
                "type": "entity",
                "confidence": e[4],
            }
            node_map[e[0]] = node
            graph_nodes.append(node)

        for c in claims_data:
            node = {
                "id": f"claim-{c['id']}",
                "name": c["statement"][:80] + ("..." if len(c["statement"]) > 80 else ""),
                "type": "claim",
                "confidence": c["confidence"],
            }
            node_map[c["id"] + 100000] = node
            graph_nodes.append(node)

        source_map: dict[str, int] = {}
        for i, s in enumerate(source_rows):
            node = {
                "id": f"source-{i}",
                "name": s[1] or s[0],
                "type": "source",
                "confidence": s[2],
            }
            source_map[s[0]] = i
            node_map[i + 200000] = node
            graph_nodes.append(node)

        graph_edges: list[dict[str, Any]] = []
        for e in edges:
            graph_edges.append({
                "source": f"entity-{e[0]}",
                "target": f"entity-{e[1]}",
                "weight": e[3],
                "type": e[2],
            })

        for c in claims_data:
            claim_node_id = f"claim-{c['id']}"
            if c.get("entity_name"):
                entity_id = None
                for e in entities:
                    if e[1] == c["entity_name"]:
                        entity_id = e[0]
                        break
                if entity_id is not None:
                    graph_edges.append({
                        "source": f"entity-{entity_id}",
                        "target": claim_node_id,
                        "weight": c["confidence"],
                        "type": "HAS_CLAIM",
                    })
            for src in c.get("sources", []):
                source_idx = source_map.get(src["url"])
                if source_idx is not None:
                    graph_edges.append({
                        "source": claim_node_id,
                        "target": f"source-{source_idx}",
                        "weight": 0.5,
                        "type": "CITED_BY",
                    })

        avg_conf = 0.0
        if claims_data:
            avg_conf = sum(c["confidence"] for c in claims_data) / len(claims_data)

        template = self._env.get_template("interactive_report.html")
        html = template.render(
            title=f"Research Report: {task_id}",
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            entities=entities,
            metrics={
                "entities": len(entities),
                "claims": len(claims_data),
                "sources": len(source_rows),
                "avg_confidence": avg_conf,
                "total_cost": (cost_report or {}).get("total_cost", 0.0),
            },
            claims=claims_data,
            sources=source_rows,
            cost_report=cost_report,
            graph_data=json.dumps({"nodes": graph_nodes, "edges": graph_edges}),
            graph_js_path="/static/graph_viz.js",
        )
        return html
