import unittest

from tripflow.persistence import SqliteDatabase


class PersistenceTests(unittest.TestCase):
    def test_initial_migration_creates_all_v1_tables(self):
        db = SqliteDatabase()
        try:
            db.migrate()
            names = {row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({
                "users", "trips", "pois", "favorite_spots", "itineraries",
                "itinerary_versions", "activities", "travel_legs", "execution_events",
            }.issubset(names))
            self.assertGreaterEqual(db.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2)
            db.migrate()
            self.assertGreaterEqual(db.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2)
        finally:
            db.close()

    def test_database_constraints_reject_invalid_activity_time(self):
        db = SqliteDatabase()
        try:
            db.migrate()
            db.connection.execute("INSERT INTO users VALUES ('u1','Test','Asia/Shanghai','2026-01-01')")
            db.connection.execute("INSERT INTO trips VALUES ('t1','u1','杭州','2026-12-01','2026-12-02','', 'draft','2026-01-01')")
            db.connection.execute("INSERT INTO itineraries VALUES ('i1','t1','主行程','draft',NULL)")
            db.connection.execute("INSERT INTO pois VALUES ('p1',NULL,'西湖','杭州',30.2,120.1,NULL,NULL,'{}')")
            with self.assertRaises(Exception):
                db.connection.execute("INSERT INTO activities VALUES ('a1','i1','p1',1,'','2026-12-01T11:00','2026-12-01T10:00','planned',0,NULL,NULL)")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
