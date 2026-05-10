User: How do Airplanes get their FlightPlan? Do they?

GitHub Copilot: Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/idl/air_traffic.idl#1-1), lines 1 to 100

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/flightplan_service/flightplan_service.py#1-1), lines 1 to 100

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/airplane_app/airplane.py#1-1), lines 1 to 100

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/airplane_app/airplane.py#100-100), lines 100 to 250

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/airplane_app/airplane.py#250-250), lines 250 to 350

Now I have a clear picture. Here's how it works:

**Yes, Airplanes file their own FlightPlan** using a Request/Reply pattern.

1. **Airplane** acts as a **Requester** — it calls `file_flight_plan()` (airplane.py), which creates a `Requester<FlightPlanRequest, FlightPlanResponse>` connected to the `"FlightPlanFilingService"` service name.

2. **FlightPlanService** acts as a **Replier** — it creates a `Replier<FlightPlanRequest, FlightPlanResponse>` with the same service name (flightplan_service.py) and validates incoming plans.

The flow:
- The airplane constructs a `FlightPlan` with its tail number, callsign, origin, destination, waypoints, and departure time, wraps it in a `FlightPlanRequest`, and sends it via `requester.send_request()`.
- It then waits up to 10 seconds for a reply (`requester.receive_replies()`).
- The `FlightPlanService` validates the plan (non-empty fields, distinct airports, valid times) and replies with accepted/rejected.
- If accepted, the service **also publishes** the plan on the `"FlightPlan"` topic via a regular DataWriter, making it available to other subscribers (towers, centers, dashboard, etc.).

So the airplane doesn't *receive* a flight plan — it **generates and files** one, then gets back an accept/reject response. The airplane already knows its route internally (it builds waypoints in `_build_waypoints()`), and the filing is essentially registering that plan with the system.

User: How are the participant entity names configured?

GitHub Copilot: Searched for text `def create_participant` (`**/connext_dds/src/common/**`), 1 result

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/common/__init__.py#164-164), lines 164 to 215

The participant entity naming is configured via two QoS fields set in `create_participant` (__init__.py):

- **`participant_qos.participant_name.name`** — set from the `participant_name` argument. In the airplane's case: `f"Airplane_{callsign}"` (e.g., `"Airplane_AAL123"`).
- **`participant_qos.participant_name.role_name`** — set from the `app_name` argument. In the airplane's case: `"ATC_Airplane"`.

These are applied on top of the base QoS loaded from the `AtcParticipantProfile` in the XML QoS file. The `name` identifies the specific participant instance, while `role_name` identifies the application type/role. Both are visible in administration tools and discovery data.
