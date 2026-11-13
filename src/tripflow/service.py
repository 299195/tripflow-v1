"""Application service backed by the existing SQLite schema."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain.errors import ValidationError
from .domain.entities import new_id
from .planner import DeterministicPlanner, PlanInput
from .persistence.database import SqliteDatabase
from .qwen_agent import QwenAgent


class TripFlowService:
    def __init__(self, db: SqliteDatabase | str | Path | None = None, planner: DeterministicPlanner | None = None, agent: QwenAgent | None = None):
        self.db = db if isinstance(db, SqliteDatabase) else SqliteDatabase(db or ":memory:")
        self.db.migrate()
        self.planner = planner or DeterministicPlanner()
        self.agent = agent or QwenAgent()

    def close(self) -> None:
        self.db.close()

    def search_pois(self, query: str, city: str | None = None) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValidationError("query is required")
        sql = "SELECT * FROM pois WHERE name LIKE ? OR address LIKE ?"
        args: list[Any] = [f"%{query}%", f"%{query}%"]
        if city:
            sql += " AND city = ?"
            args.append(city)
        return [self._poi_row(r) for r in self.db.connection.execute(sql, args)]

    def confirm_poi(self, poi_id: str) -> dict[str, Any]:
        row = self.db.connection.execute("SELECT * FROM pois WHERE id = ? OR amap_id = ?", (poi_id, poi_id)).fetchone()
        if not row:
            raise KeyError("POI not found")
        return self._poi_row(row)

    def create_trip(self, data: dict[str, Any]) -> dict[str, Any]:
        user_id = data.get("user_id") or new_id()
        now = self._now()
        c = self.db.connection
        c.execute("INSERT OR IGNORE INTO users(id,display_name,timezone,created_at) VALUES(?,?,?,?)", (user_id, data.get("display_name", "默认用户"), data.get("timezone", "Asia/Shanghai"), now))
        trip_id = new_id()
        c.execute("INSERT INTO trips(id,user_id,city,start_date,end_date,title,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (trip_id, user_id, data["city"], data["start_date"], data["end_date"], data.get("title", ""), "draft", now))
        itinerary_id = new_id()
        c.execute("INSERT INTO itineraries(id,trip_id,name,status,current_version_id) VALUES(?,?,?,?,NULL)", (itinerary_id, trip_id, data.get("itinerary_name", "主行程"), "draft"))
        c.commit()
        return {"id": trip_id, "user_id": user_id, "itinerary_id": itinerary_id, "status": "draft", "city": data["city"]}

    def save_poi(self, data: dict[str, Any]) -> dict[str, Any]:
        poi_id = data.get("id") or new_id()
        self.db.connection.execute("INSERT OR REPLACE INTO pois(id,amap_id,name,city,latitude,longitude,address,category,raw_data_json) VALUES(?,?,?,?,?,?,?,?,?)", (poi_id, data.get("amap_id"), data["name"], data["city"], data["latitude"], data["longitude"], data.get("address"), data.get("category"), json.dumps(data.get("raw_data", {}), ensure_ascii=False)))
        self.db.connection.commit()
        return self.confirm_poi(poi_id)

    def favorite(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        poi = self.confirm_poi(data["poi_id"])
        favorite_id = new_id()
        self.db.connection.execute("INSERT OR IGNORE INTO users(id,display_name,timezone,created_at) VALUES(?,?,?,?)", (user_id, "默认用户", "Asia/Shanghai", self._now()))
        self.db.connection.execute("INSERT OR REPLACE INTO favorite_spots(id,user_id,poi_id,note,preference_tags_json,created_at) VALUES(?,?,?,?,?,?)", (favorite_id, user_id, poi["id"], data.get("note"), json.dumps(data.get("preference_tags", []), ensure_ascii=False), self._now()))
        self.db.connection.commit()
        return {"id": favorite_id, "user_id": user_id, "poi_id": poi["id"], "note": data.get("note"), "preference_tags": data.get("preference_tags", [])}

    def profile(self, user_id: str) -> dict[str, Any]:
        user = self.db.connection.execute("SELECT id,display_name,timezone,created_at FROM users WHERE id=?", (user_id,)).fetchone()
        favorites = []
        for row in self.db.connection.execute("SELECT f.id AS favorite_id,f.note,f.preference_tags_json,p.* FROM favorite_spots f JOIN pois p ON p.id=f.poi_id WHERE f.user_id=? ORDER BY f.created_at DESC", (user_id,)):
            item = self._poi_row(row)
            item["preference_tags"] = json.loads(item.pop("preference_tags_json"))
            favorites.append(item)
        trips = [dict(row) for row in self.db.connection.execute("SELECT t.*,i.id AS itinerary_id,i.current_version_id FROM trips t LEFT JOIN itineraries i ON i.trip_id=t.id WHERE t.user_id=? ORDER BY t.created_at DESC", (user_id,))]
        return {"user": dict(user) if user else {"id": user_id, "display_name": "旅行者"}, "favorites": favorites, "trips": trips}

    def generate_itinerary(self, trip_id: str, data: dict[str, Any]) -> dict[str, Any]:
        trip = self.db.connection.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if not trip:
            raise KeyError("trip not found")
        poi_ids = data["poi_ids"]
        pois = {str(r["id"]): self._poi_row(r) for r in self.db.connection.execute(f"SELECT * FROM pois WHERE id IN ({','.join('?' for _ in poi_ids)})", poi_ids)}
        result = self.planner.plan(PlanInput(city=trip["city"], date=data.get("date", trip["start_date"]), poi_ids=poi_ids, pois=pois, start=data.get("start", "09:00"), end=data.get("end", "18:00"), stay_minutes=data.get("stay_minutes"), fixed_booking=data.get("fixed_booking"), route_overrides=data.get("route_overrides")))
        itinerary = self.db.connection.execute("SELECT * FROM itineraries WHERE trip_id = ?", (trip_id,)).fetchone()
        self.db.connection.execute("DELETE FROM travel_legs WHERE itinerary_id = ?", (itinerary["id"],))
        self.db.connection.execute("DELETE FROM activities WHERE itinerary_id = ?", (itinerary["id"],))
        activity_ids: list[str] = []
        for a in result.activities:
            aid = new_id(); activity_ids.append(aid)
            self.db.connection.execute("INSERT INTO activities(id,itinerary_id,poi_id,sequence,title,starts_at,ends_at,status,reservation_required,reservation_ref,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (aid, itinerary["id"], a.poi_id, a.sequence, a.title, a.starts_at, a.ends_at, "planned", int(a.reservation_required), a.reservation_ref, None))
        for leg, from_id, to_id in zip(result.legs, activity_ids, activity_ids[1:]):
            self.db.connection.execute("INSERT INTO travel_legs(id,itinerary_id,from_activity_id,to_activity_id,mode,duration_minutes,distance_meters,route_data_json) VALUES(?,?,?,?,?,?,?,?)", (new_id(), itinerary["id"], from_id, to_id, "walking", leg.duration_minutes, leg.distance_meters, json.dumps({"source": leg.source})))
        self.db.connection.execute("UPDATE trips SET status='ready' WHERE id = ?", (trip_id,))
        snapshot = self._snapshot(itinerary["id"], trip_id)
        version = new_id()
        count = self.db.connection.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM itinerary_versions WHERE itinerary_id=?", (itinerary["id"],)).fetchone()[0]
        self.db.connection.execute("INSERT INTO itinerary_versions(id,itinerary_id,version_number,change_reason,snapshot_json,created_at) VALUES(?,?,?,?,?,?)", (version, itinerary["id"], count, "确定性规划", json.dumps(snapshot, ensure_ascii=False), self._now()))
        self.db.connection.execute("UPDATE itineraries SET current_version_id=?, status='confirmed' WHERE id=?", (version, itinerary["id"]))
        self.db.connection.commit()
        response = self.get_itinerary(itinerary["id"])
        response["agent"] = self.agent.explain_plan({"city": trip["city"], "date": data.get("date", trip["start_date"]), "activities": [a.__dict__ if hasattr(a, "__dict__") else {"poi_id": a.poi_id, "starts_at": a.starts_at, "ends_at": a.ends_at} for a in result.activities], "legs": [l.__dict__ if hasattr(l, "__dict__") else {"from_poi_id": l.from_poi_id, "to_poi_id": l.to_poi_id, "duration_minutes": l.duration_minutes} for l in result.legs]}) or {"status": "fallback", "mode": "deterministic_fallback", "reason": "Qwen unavailable"}
        return response

    def edit_itinerary(self, itinerary_id: str, data: dict[str, Any]) -> dict[str, Any]:
        row = self._itinerary(itinerary_id); op = data["operation"]
        if op == "delete":
            targets = [r["id"] for r in self.db.connection.execute("SELECT id FROM activities WHERE itinerary_id=? AND poi_id=?", (itinerary_id, data["poi_id"]))]
            for activity_id in targets:
                self.db.connection.execute("DELETE FROM travel_legs WHERE from_activity_id=? OR to_activity_id=?", (activity_id, activity_id))
            self.db.connection.execute("DELETE FROM activities WHERE itinerary_id=? AND poi_id=?", (itinerary_id, data["poi_id"]))
        elif op == "replace": self.db.connection.execute("UPDATE activities SET poi_id=? WHERE itinerary_id=? AND poi_id=?", (data["to_poi_id"], itinerary_id, data["from_poi_id"]))
        elif op == "extend":
            a = self.db.connection.execute("SELECT * FROM activities WHERE itinerary_id=? AND poi_id=?", (itinerary_id, data["poi_id"])).fetchone()
            if not a: raise KeyError("activity not found")
            from datetime import datetime, timedelta
            end = datetime.fromisoformat(a["ends_at"]) + timedelta(minutes=int(data["additional_minutes"]))
            self.db.connection.execute("UPDATE activities SET ends_at=? WHERE id=?", (end.isoformat(timespec="minutes"), a["id"]))
        else: raise ValidationError("unsupported edit operation")
        self._validate_db_schedule(itinerary_id)
        return self._new_version(itinerary_id, data.get("change_reason", f"手动编辑: {op}"), row["trip_id"])

    def list_versions(self, itinerary_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection.execute("SELECT id,version_number,change_reason,created_at,restored_from_version_id FROM itinerary_versions WHERE itinerary_id=? ORDER BY version_number", (itinerary_id,))]

    def restore_version(self, itinerary_id: str, version_id: str, reason: str = "恢复历史版本") -> dict[str, Any]:
        source = self.db.connection.execute("SELECT * FROM itinerary_versions WHERE id=? AND itinerary_id=?", (version_id, itinerary_id)).fetchone()
        if not source: raise KeyError("version not found")
        snapshot = json.loads(source["snapshot_json"])
        self.db.connection.execute("DELETE FROM activities WHERE itinerary_id=?", (itinerary_id,))
        self.db.connection.execute("DELETE FROM travel_legs WHERE itinerary_id=?", (itinerary_id,))
        for a in snapshot["activities"]:
            self.db.connection.execute("INSERT INTO activities(id,itinerary_id,poi_id,sequence,title,starts_at,ends_at,status,reservation_required,reservation_ref,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (a["id"], itinerary_id, a["poi_id"], a["sequence"], a.get("title", ""), a["starts_at"], a["ends_at"], a.get("status", "planned"), int(a.get("reservation_required", False)), a.get("reservation_ref"), a.get("note")))
        for leg in snapshot.get("travel_legs", []):
            self.db.connection.execute("INSERT INTO travel_legs(id,itinerary_id,from_activity_id,to_activity_id,mode,duration_minutes,distance_meters,route_data_json) VALUES(?,?,?,?,?,?,?,?)", (leg["id"], itinerary_id, leg["from_activity_id"], leg["to_activity_id"], leg["mode"], leg["duration_minutes"], leg["distance_meters"], leg.get("route_data_json", "{}")))
        return self._new_version(itinerary_id, reason, snapshot["itinerary"]["trip_id"], source["id"])

    def execution_event(self, itinerary_id: str, data: dict[str, Any]) -> dict[str, Any]:
        event_id = new_id(); self.db.connection.execute("INSERT INTO execution_events(id,itinerary_id,activity_id,event_type,occurred_at,note) VALUES(?,?,?,?,?,?)", (event_id, itinerary_id, data.get("activity_id"), data["event_type"], data.get("occurred_at", self._now()), data.get("note"))); self.db.connection.commit(); return {"id": event_id, **data}

    def get_itinerary(self, itinerary_id: str) -> dict[str, Any]:
        row = self._itinerary(itinerary_id); return {"id": itinerary_id, "trip_id": row["trip_id"], "status": row["status"], "activities": [dict(x) for x in self.db.connection.execute("SELECT * FROM activities WHERE itinerary_id=? ORDER BY sequence", (itinerary_id,))], "travel_legs": [dict(x) for x in self.db.connection.execute("SELECT * FROM travel_legs WHERE itinerary_id=?", (itinerary_id,))]}

    def _new_version(self, itinerary_id: str, reason: str, trip_id: str, origin_id: str | None = None) -> dict[str, Any]:
        snapshot = self._snapshot(itinerary_id, trip_id); version = new_id(); count = self.db.connection.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM itinerary_versions WHERE itinerary_id=?", (itinerary_id,)).fetchone()[0]
        self.db.connection.execute("INSERT INTO itinerary_versions(id,itinerary_id,version_number,change_reason,snapshot_json,restored_from_version_id,created_at) VALUES(?,?,?,?,?,?,?)", (version,itinerary_id,count,reason,json.dumps(snapshot,ensure_ascii=False),origin_id,self._now())); self.db.connection.execute("UPDATE itineraries SET current_version_id=? WHERE id=?", (version,itinerary_id)); self.db.connection.commit(); return self.get_itinerary(itinerary_id) | {"new_version_id": version, "version_number": count}

    def _snapshot(self, itinerary_id: str, trip_id: str) -> dict[str, Any]: return {"itinerary": {"id": itinerary_id, "trip_id": trip_id}, "activities": [dict(x) for x in self.db.connection.execute("SELECT * FROM activities WHERE itinerary_id=? ORDER BY sequence", (itinerary_id,))], "travel_legs": [dict(x) for x in self.db.connection.execute("SELECT * FROM travel_legs WHERE itinerary_id=?", (itinerary_id,))]}
    def _validate_db_schedule(self, itinerary_id: str) -> None:
        rows = list(self.db.connection.execute("SELECT starts_at,ends_at,reservation_required,reservation_ref FROM activities WHERE itinerary_id=? ORDER BY starts_at", (itinerary_id,)))
        for a,b in zip(rows, rows[1:]):
            if b["starts_at"] < a["ends_at"]: raise ValidationError("activities overlap")
        if any(r["reservation_required"] and not r["reservation_ref"] for r in rows): raise ValidationError("reservation reference is required")
    def _itinerary(self, itinerary_id: str):
        row = self.db.connection.execute("SELECT * FROM itineraries WHERE id=?", (itinerary_id,)).fetchone()
        if not row: raise KeyError("itinerary not found")
        return row
    @staticmethod
    def _poi_row(row):
        d = dict(row); d["raw_data"] = json.loads(d.pop("raw_data_json", "{}")); return d
    @staticmethod
    def _now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
