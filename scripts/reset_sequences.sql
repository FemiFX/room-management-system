-- Reset id sequences after restoring inventory data into a fresh DB.
-- Run AFTER loading the pg_dump --data-only export of buildings/floors/rooms/keys/room_equipment/internet_connections.
-- Each setval(..., COALESCE(MAX(id),0)+1, false) makes the NEXT inserted row get MAX(id)+1.

SELECT setval('buildings_id_seq',           (SELECT COALESCE(MAX(id),0)+1 FROM buildings),           false);
SELECT setval('floors_id_seq',              (SELECT COALESCE(MAX(id),0)+1 FROM floors),              false);
SELECT setval('rooms_id_seq',               (SELECT COALESCE(MAX(id),0)+1 FROM rooms),               false);
SELECT setval('keys_id_seq',                (SELECT COALESCE(MAX(id),0)+1 FROM keys),                false);
SELECT setval('room_equipment_id_seq',      (SELECT COALESCE(MAX(id),0)+1 FROM room_equipment),      false);
SELECT setval('internet_connections_id_seq',(SELECT COALESCE(MAX(id),0)+1 FROM internet_connections),false);
