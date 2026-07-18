import argparse
import os
import sys
import psycopg2
import psycopg2.extras
 
 
def source_dsn(arg):
    if arg:
        return arg
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    pw = os.environ.get("PGPASSWORD", "postgres")
    return f"host=localhost port=5432 dbname=risk_signal_db user=postgres password={pw}"
 
FETCH = {
    "companies": (
        "SELECT id, ticker, name, cik, sector, sic_code, created_at "
        "FROM companies ORDER BY id",
        "id, ticker, name, cik, sector, sic_code, created_at",
    ),
    "news_articles": (
        "SELECT id, url, headline, NULL::text AS body, source, published_at, "
        "sentiment_label, sentiment_score, processed, created_at "
        "FROM news_articles "
        "WHERE id IN ("
        "  SELECT DISTINCT ac.article_id "
        "  FROM article_companies ac "
        "  JOIN alerts a ON a.company_id = ac.company_id "
        "  JOIN news_articles n2 ON n2.id = ac.article_id "
        "  WHERE n2.published_at::date = a.triggered_at::date"
        ") "
        "ORDER BY id",
        "id, url, headline, body, source, published_at, sentiment_label, "
        "sentiment_score, processed, created_at",
    ),
    "article_companies": (
        "SELECT ac.id, ac.article_id, ac.company_id, ac.created_at "
        "FROM article_companies ac "
        "WHERE ac.article_id IN ("
        "  SELECT DISTINCT ac2.article_id "
        "  FROM article_companies ac2 "
        "  JOIN alerts a ON a.company_id = ac2.company_id "
        "  JOIN news_articles n2 ON n2.id = ac2.article_id "
        "  WHERE n2.published_at::date = a.triggered_at::date"
        ") "
        "ORDER BY ac.id",
        "id, article_id, company_id, created_at",
    ),
    "alerts": (
        "SELECT id, company_id, triggered_at, alert_type, severity, explanation, resolved "
        "FROM alerts ORDER BY id",
        "id, company_id, triggered_at, alert_type, severity, explanation, resolved",
    ),
    "alert_explanations": (
        "SELECT id, alert_id, status, narrative, cited_ids, model, abstain_reason, created_at "
        "FROM alert_explanations ORDER BY id",
        "id, alert_id, status, narrative, cited_ids, model, abstain_reason, created_at",
    ),
}
 
SEQUENCES = [
    ("companies_id_seq", "companies"),
    ("news_articles_id_seq", "news_articles"),
    ("article_companies_id_seq", "article_companies"),
    ("alerts_id_seq", "alerts"),
    ("alert_explanations_id_seq", "alert_explanations"),
]
 
 
def fetch_all(src):
    data = {}
    with src.cursor() as cur:
        for table, (query, _cols) in FETCH.items():
            cur.execute(query)
            rows = cur.fetchall()
            data[table] = rows
            print(f"  {table:20} {len(rows):>6} rows")
    return data
 
 
def load_into(target_dsn, data):
    print(f"Loading into target ...")
    conn = psycopg2.connect(target_dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SET search_path TO public;")
            for table, (_q, cols) in FETCH.items():
                rows = data[table]
                if not rows:
                    continue
                placeholders = "(" + ",".join(["%s"] * len(rows[0])) + ")"
                psycopg2.extras.execute_values(
                    cur,
                    f"INSERT INTO public.{table} ({cols}) VALUES %s "
                    f"ON CONFLICT DO NOTHING",
                    rows, template=placeholders,
                )
                print(f"  inserted {table}: {len(rows)} rows")
            for seq, table in SEQUENCES:
                cur.execute(
                    f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1));")
            cur.execute("SELECT setval('api_keys_id_seq', 1);")
        print("Load complete.")
    finally:
        conn.close()
 
 
def write_sql(path, data):
    print(f"Writing {path} ...")
    with open(path, "w", encoding="utf-8") as f:
        f.write("-- Trimmed demo data. Load AFTER the schema is created.\n")
        f.write("-- api_keys intentionally empty; the app mints demo keys on demand.\n")
        f.write("-- Rows are ordered by FK dependency, so no deferred FK checks needed.\n")
        f.write("BEGIN;\n\n")
        for table, (_q, cols) in FETCH.items():
            rows = data[table]
            if not rows:
                continue
            f.write(f"INSERT INTO public.{table} ({cols}) VALUES\n")
            lines = []
            for r in rows:
                vals = ",".join(_sql_literal(v) for v in r)
                lines.append(f"  ({vals})")
            f.write(",\n".join(lines))
            f.write("\nON CONFLICT DO NOTHING;\n\n")
        for seq, table in SEQUENCES:
            f.write(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1));\n")
        f.write("SELECT setval('api_keys_id_seq', 1);\nCOMMIT;\n")
 
 
def _sql_literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):  # integer[] like cited_ids
        return "'{" + ",".join(str(x) for x in v) + "}'"
    # dates, strings: escape single quotes
    s = str(v).replace("'", "''")
    return f"'{s}'"
 
 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="source DSN (default: DATABASE_URL or local)")
    ap.add_argument("--target", help="target DSN to load into directly (e.g. Neon)")
    ap.add_argument("--out", help="write a portable .sql file instead of/in addition to loading")
    args = ap.parse_args()
 
    if not args.target and not args.out:
        sys.exit("Nothing to do: pass --target (load into Neon) and/or --out (write .sql).")
 
    print("Fetching trimmed data from source ...")
    src = psycopg2.connect(source_dsn(args.source))
    try:
        data = fetch_all(src)
    finally:
        src.close()
 
    if args.out:
        write_sql(args.out, data)
    if args.target:
        load_into(args.target, data)
    print("Done.")
 
 
if __name__ == "__main__":
    main()