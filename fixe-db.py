import psycopg2

DATABASE_URL = "postgresql://flask_db_og3x_user:Tt4E8iwXus67j7mpZxCfoWna4GiZwzNE@dpg-d7p7sve8bjmc739m1b3g-a.virginia-postgres.render.com/flask_db_og3x"

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

# 1. mamafa doublon raha misy
cur.execute("""
DELETE FROM stats_produit
WHERE id NOT IN (
    SELECT MIN(id)
    FROM stats_produit
    GROUP BY produit_id, user_id
);
""")

# 2. manampy contrainte unique
cur.execute("""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_stats'
    ) THEN
        ALTER TABLE stats_produit
        ADD CONSTRAINT uq_stats UNIQUE (produit_id, user_id);
    END IF;
END $$;
""")

conn.commit()
cur.close()
conn.close()

print("OK DB FIXED")