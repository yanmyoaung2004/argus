from argus.services.knowledge_graph.schema import init_db
from argus.shared.config import settings

db = init_db(settings.sqlite_path)
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
for t in ["entities", "claims", "sources"]:
    rows = db.execute(f"SELECT count(*) FROM {t}").fetchone()
    print(f"{t}: {rows[0]}")
    data = db.execute(f"SELECT * FROM {t} LIMIT 3").fetchall()
    for row in data:
        print(f"  {row}")
db.close()
