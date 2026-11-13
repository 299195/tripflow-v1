CREATE TABLE users (
    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, timezone TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE trips (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), city TEXT NOT NULL,
    start_date TEXT NOT NULL, end_date TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('draft','planning','ready','in_progress','completed','cancelled')),
    created_at TEXT NOT NULL, CHECK (end_date >= start_date)
);
CREATE TABLE pois (
    id TEXT PRIMARY KEY, amap_id TEXT UNIQUE, name TEXT NOT NULL, city TEXT NOT NULL,
    latitude REAL NOT NULL, longitude REAL NOT NULL, address TEXT, category TEXT,
    raw_data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE favorite_spots (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), poi_id TEXT NOT NULL REFERENCES pois(id),
    note TEXT, preference_tags_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
    UNIQUE(user_id, poi_id)
);
CREATE TABLE itineraries (
    id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(id), name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','confirmed','active','completed','archived')),
    current_version_id TEXT
);
CREATE TABLE itinerary_versions (
    id TEXT PRIMARY KEY, itinerary_id TEXT NOT NULL REFERENCES itineraries(id), version_number INTEGER NOT NULL,
    change_reason TEXT NOT NULL, snapshot_json TEXT NOT NULL, restored_from_version_id TEXT REFERENCES itinerary_versions(id),
    created_at TEXT NOT NULL, UNIQUE(itinerary_id, version_number)
);
CREATE TABLE activities (
    id TEXT PRIMARY KEY, itinerary_id TEXT NOT NULL REFERENCES itineraries(id), poi_id TEXT NOT NULL REFERENCES pois(id),
    sequence INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned','confirmed','in_progress','completed','skipped','cancelled')),
    reservation_required INTEGER NOT NULL DEFAULT 0, reservation_ref TEXT, note TEXT,
    UNIQUE(itinerary_id, sequence), CHECK (ends_at > starts_at)
);
CREATE TABLE travel_legs (
    id TEXT PRIMARY KEY, itinerary_id TEXT NOT NULL REFERENCES itineraries(id),
    from_activity_id TEXT NOT NULL REFERENCES activities(id), to_activity_id TEXT NOT NULL REFERENCES activities(id),
    mode TEXT NOT NULL CHECK (mode IN ('walking','transit','driving','bicycling')),
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes >= 0), distance_meters INTEGER NOT NULL CHECK (distance_meters >= 0),
    route_data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE execution_events (
    id TEXT PRIMARY KEY, itinerary_id TEXT NOT NULL REFERENCES itineraries(id), activity_id TEXT REFERENCES activities(id),
    event_type TEXT NOT NULL CHECK (event_type IN ('started','arrived','completed','skipped','note')),
    occurred_at TEXT NOT NULL, note TEXT
);
CREATE INDEX idx_activities_itinerary_sequence ON activities(itinerary_id, sequence);
CREATE INDEX idx_execution_events_itinerary_time ON execution_events(itinerary_id, occurred_at);
