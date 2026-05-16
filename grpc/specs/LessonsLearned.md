# Lessons Learned — gRPC ATC Demo Implementation

## Error Log

### 1. Missing `write_sim_speed` in common.py
- **Error:** `ImportError: cannot import name 'write_sim_speed' from 'common'`
- **File:** `app_dashboard.py` imports `write_sim_speed` from `common`
- **Cause:** Dashboard needs to persist sim speed changes to the config JSON file for restarts. The function was referenced in the dashboard but never defined in `common.py`.
- **Fix:** Added `write_sim_speed(speed, config_path)` function to `common.py` that reads the scenario JSON, updates the `initial_speed` key, and writes it back.

### 2. Wrong protobuf enum name `InstructionFilter` in app_dashboard.py
- **Error:** `AttributeError: module 'air_traffic_types_pb2' has no attribute 'InstructionFilter'`
- **File:** `app_dashboard.py` lines 356, 387, 418 (tower, TRACON, center stream methods)
- **Cause:** The proto file defines the message as `ControllerInstructionFilter`, not `InstructionFilter`. The shorter name was used during code generation.
- **Fix:** Replaced `pb.InstructionFilter()` with `pb.ControllerInstructionFilter()` in all three stream methods (`_stream_tower`, `_stream_tracon`, `_stream_center`).

### 3. Wrong protobuf enum name `Severity` in app_dashboard.py
- **Error:** `AttributeError: module 'air_traffic_types_pb2' has no attribute 'Severity'`
- **File:** `app_dashboard.py` line 157, `alert_dict()` function
- **Cause:** The proto file defines the enum as `AlertSeverity`, not `Severity`. There is also a separate `ConvectiveSeverity` enum, so the prefix is needed to disambiguate.
- **Fix:** Replaced `pb.Severity.Name(s.severity)` with `pb.AlertSeverity.Name(s.severity)`.

### 4. Wrong protobuf enum name `NavigationStatus` in app_dashboard.py
- **Error:** Would produce `AttributeError: module 'air_traffic_types_pb2' has no attribute 'NavigationStatus'` when aircraft tracking data reaches the dashboard.
- **File:** `app_dashboard.py` line 114, `tracking_dict()` function
- **Cause:** The proto file defines the enum as `NavStatus`, not `NavigationStatus`.
- **Fix:** Replaced `pb.NavigationStatus.Name(s.nav_status)` with `pb.NavStatus.Name(s.nav_status)`.

### 5. gRPC thread pool exhaustion causing DEADLINE_EXCEEDED on flight plan filing
- **Error:** `StatusCode.DEADLINE_EXCEEDED` — all airplanes fail to file flight plans.
- **File:** `common.py` `create_grpc_server()`, affects `app_flightplan_service.py` and `app_weather_service.py`
- **Cause:** The default `max_workers=10` thread pool was too small. The scenario has 20 centers, each holding a long-lived `StreamFlightPlans` server-streaming RPC that pins a worker thread. After 10 connections, the pool was fully exhausted and no unary `FileFlightPlan` calls could be serviced. In gRPC Python, each active server-streaming RPC occupies a thread for the entire stream duration.
- **Fix:** Increased `max_workers` default from 10 to 50 in `create_grpc_server()`. Rule of thumb: pool size ≥ max concurrent streaming clients + headroom for unary RPCs.

### 6. Dashboard (and other apps) hang on Ctrl+C / SIGTERM
- **Error:** Process does not exit after Ctrl+C; requires `kill -9`.
- **File:** `common.py` `install_signal_handlers()`
- **Cause:** The signal handler only set `shutdown_event`, but the dashboard has many daemon threads with 600-second gRPC stream timeouts, plus Flask's `app.run()` blocking the main thread. These threads don't check `shutdown_event` frequently enough to terminate promptly.
- **Fix:** Enhanced `install_signal_handlers()` to start a 2-second force-exit timer (`os._exit(0)`) on first signal, and immediately `os._exit(1)` on a second signal. This ensures all apps terminate cleanly within 2 seconds.

### 7. Zeroconf `NonUniqueNameException` after kill -9
- **Error:** `zeroconf._exceptions.NonUniqueNameException` — services crash on startup after a previous unclean shutdown.
- **File:** `common.py` `ZeroconfRegistrar.register()`
- **Cause:** When processes are killed with `kill -9` or `demo_stop.sh`, the Zeroconf cleanup (`zc.close()`) never runs. Stale mDNS/DNS-SD records persist on the local network. On the next startup, `register_service()` detects the duplicate name and raises `NonUniqueNameException`.
- **Fix:** Use `cooperating_responders=True` in `register_service()`. This tells Zeroconf that multiple responders for the same service name are expected, allowing the new instance to override the stale record.

### 8. Zeroconf property keys are bytes, not strings — breaks all discovery-based filtering
- **Error:** All handoffs fail silently. Centers see every aircraft as UNCOORDINATED because towers, TRACONs, and centers can't discover each other's services by property filtering.
- **File:** `common.py` `ServiceListener.add_service()`
- **Cause:** Zeroconf stores mDNS TXT record keys as `bytes`. The `add_service()` method decoded property **values** (`v.decode()`) but not **keys**, resulting in dicts like `{b'origin': 'KJFK', ...}`. All app code uses string keys (`props.get("origin", "")`) which always returned the default empty string. This caused towers to skip all aircraft (origin didn't match), TRACONs to skip all aircraft, and the entire handoff chain to fail.
- **Fix:** Decode both keys and values in the property dict comprehension: `{k.decode() if isinstance(k, bytes) else str(k): v.decode() ...}`.

### 9. Hardcoded PORT_MAP unnecessary with Zeroconf discovery
- **Error:** Design inconsistency — not a runtime error, but contradicts the Zeroconf-based architecture.
- **Files:** `app_airport.py`, `app_tower.py`, `app_tracon.py`, `app_center.py`, `app_flightplan_service.py`, `app_weather_service.py`
- **Cause:** Each app had a hardcoded `PORT_MAP` dict (e.g., `{"KJFK": 50100, ...}`) or hardcoded default port numbers (FPS: 50052, Weather: 50053). With Zeroconf mDNS/DNS-SD handling service discovery, static port assignments are unnecessary and defeat the purpose of dynamic discovery.
- **Fix:** Removed all `PORT_MAP` dictionaries. Changed all `--port` argument defaults to `0` (OS auto-assign). Zeroconf advertises the actual port, and `DiscoveryManager.get_endpoint()` resolves it at runtime. The `--port` CLI flag still allows manual overrides if needed.

### 10. Only 3 of 10 aircraft file flight plans — Zeroconf discovery race condition
- **Error:** Most aircraft log `FlightPlanService not discovered, proceeding without filing`. Only the last few aircraft (launched later) successfully file.
- **File:** `app_airplane.py` `file_flight_plan()`
- **Cause:** `file_flight_plan()` called `discovery.get_endpoint("fps", "fps")` once and gave up immediately if it returned `None`. Aircraft are launched 0.3s apart in `demo_start.sh`, so the first aircraft start before the FPS mDNS record has propagated through Zeroconf. This is a classic service discovery race condition — analogous to DDS discovery needing time for endpoint matching.
- **Fix:** Added a retry loop: up to 10 attempts with 0.5s sleep between each (5s total timeout). This gives Zeroconf enough time to propagate the FPS service record before the aircraft gives up.

### 11. Sequential instruction subscription blocks weather deviations — airplane never reaches center streams
- **Error:** Aircraft fly through convective cells without deviating. Centers log `WEATHER DEVIATION` instructions, but aircraft never execute them.
- **File:** `app_airplane.py` `_subscribe_instructions()`
- **Cause:** The airplane iterated through ALL discovered controller services **sequentially** — 7 towers, 7 TRACONs, 20 centers — opening a gRPC stream to each with a `timeout=30` deadline. Total cycle time: 34 services × 30s = 1020s. In a 120-second demo, the airplane could reach at most ~4 services, never getting past the towers. It never listened to the center that issued the weather-deviation HEADING instruction. This is a fundamental mismatch with the DDS pub/sub model where a single DataReader receives from all matching DataWriters simultaneously.
- **Fix:** Restructured `_subscribe_instructions()` to spawn a **parallel thread per discovered service**. A discovery loop polls for new services every 3 seconds and starts a dedicated `_stream_instructions_from()` thread for each unique `(host, port)`. Each thread maintains a persistent stream to one controller with `timeout=60` and auto-reconnects on failure. This mirrors DDS's parallel data delivery model — the airplane now receives instructions from all controllers concurrently.

### 12. Weather cells published too infrequently — centers have stale or missing cell data
- **Error:** Aircraft fly through convective cells without being deviated, even when the center is correctly checking for weather conflicts.
- **Files:** `app_weather_service.py`, `app_center.py` `_subscribe_weather_cells()`
- **Cause:** Two related issues:
  1. **Publish interval too long:** `WeatherServiceServicer` had `publish_interval_s=300` (5 sim-minutes). Cells are published on spawn, but subsequent position updates only come every 5 sim-minutes. Centers that subscribe after the spawn burst — or centers that take handoffs of aircraft near cells they never received — have stale/missing cell data. In contrast, DDS would continuously distribute updates via its wire protocol.
  2. **Stale cells never pruned:** The center's `_active_cells` dict grew monotonically. Expired/dissipated cells remained in the dict forever because nothing removed them. The center could be checking distances against cells that no longer exist.
- **Fix:**
  1. Reduced `publish_interval_s` from 300 to 10 sim-time seconds, so all 20 centers receive current cell positions every ~1 wall second.
  2. Added stale-cell pruning in `_subscribe_weather_cells()`: after a batch of updates arrives, cells NOT present in the latest publish cycle are removed from `_active_cells`.

### 13. Dashboard-injected weather cells are visual-only — centers never receive them
- **Error:** Cells created via the dashboard "Inject Cell" button appear on the map but aircraft fly straight through them without deviating.
- **Files:** `app_dashboard.py` `create_weather_cell()`, `air_traffic_types.proto`, `app_weather_service.py`
- **Cause:** The dashboard stored injected cells in its local `state["convective_cells"]` dict only. No gRPC call was made to the WeatherService, so the cells were never published to centers via `StreamConvectiveCells`. Centers had no knowledge of these cells. In DDS, the equivalent would be like writing a sample to a topic that no subscriber can discover.
- **Fix:**
  1. Added `InjectCell(ConvectiveCell) returns (CellInjectionAck)` RPC to the `WeatherService` proto definition and regenerated stubs.
  2. Implemented `InjectCell` in `WeatherServiceServicer` — creates an `ActiveCell` from the proto, adds it to the cell pool, and publishes it via the `StreamBroadcaster` so all subscribed centers receive it immediately.
  3. Updated `create_weather_cell()` in the dashboard to discover the WeatherService via Zeroconf and call `InjectCell` before storing locally. Cells now flow through the same path as naturally-spawned cells: `Dashboard → WeatherService → StreamConvectiveCells → Centers → check_weather_cells → HEADING instruction → Aircraft`.
