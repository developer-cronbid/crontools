import sqlite3
conn = sqlite3.connect('db.sqlite3')

# Drop all video tables
tables_to_drop = [
    'video_generatedvideo',
    'video_generatedvideopost',
    'video_generatedvideoplan',
    'video_videoprofile',
]
for t in tables_to_drop:
    try:
        conn.execute(f"DROP TABLE IF EXISTS {t};")
        print(f"Dropped {t}")
    except Exception as e:
        print(f"Error dropping {t}: {e}")

# Clear all video migration records
conn.execute("DELETE FROM django_migrations WHERE app='video';")
conn.commit()
print("Cleared video migration records")
conn.close()
print("Done.")
