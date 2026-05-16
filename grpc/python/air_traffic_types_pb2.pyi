import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FlightPhase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FLIGHT_PHASE_UNKNOWN: _ClassVar[FlightPhase]
    PREFLIGHT: _ClassVar[FlightPhase]
    TAXI_OUT: _ClassVar[FlightPhase]
    TAKEOFF: _ClassVar[FlightPhase]
    CLIMB: _ClassVar[FlightPhase]
    CRUISE: _ClassVar[FlightPhase]
    DESCENT: _ClassVar[FlightPhase]
    APPROACH: _ClassVar[FlightPhase]
    LANDING: _ClassVar[FlightPhase]
    TAXI_IN: _ClassVar[FlightPhase]
    PARKED: _ClassVar[FlightPhase]
    HOLDING: _ClassVar[FlightPhase]

class InstructionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INSTRUCTION_TYPE_UNKNOWN: _ClassVar[InstructionType]
    HEADING: _ClassVar[InstructionType]
    ALTITUDE: _ClassVar[InstructionType]
    SPEED: _ClassVar[InstructionType]
    CLEARANCE: _ClassVar[InstructionType]
    HOLD: _ClassVar[InstructionType]
    GO_AROUND: _ClassVar[InstructionType]
    TAXI: _ClassVar[InstructionType]
    PUSHBACK: _ClassVar[InstructionType]

class AcknowledgmentStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACKNOWLEDGMENT_STATUS_UNKNOWN: _ClassVar[AcknowledgmentStatus]
    RECEIVED: _ClassVar[AcknowledgmentStatus]
    WILCO: _ClassVar[AcknowledgmentStatus]
    UNABLE: _ClassVar[AcknowledgmentStatus]
    READBACK_CORRECT: _ClassVar[AcknowledgmentStatus]
    READBACK_INCORRECT: _ClassVar[AcknowledgmentStatus]

class FlightPlanStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FLIGHT_PLAN_STATUS_UNKNOWN: _ClassVar[FlightPlanStatus]
    FILED: _ClassVar[FlightPlanStatus]
    ACTIVE: _ClassVar[FlightPlanStatus]
    AMENDED: _ClassVar[FlightPlanStatus]
    DELAYED: _ClassVar[FlightPlanStatus]
    CANCELLED: _ClassVar[FlightPlanStatus]
    COMPLETED: _ClassVar[FlightPlanStatus]

class RunwayOperationalStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RUNWAY_STATUS_UNKNOWN: _ClassVar[RunwayOperationalStatus]
    OPEN: _ClassVar[RunwayOperationalStatus]
    CLOSED: _ClassVar[RunwayOperationalStatus]
    OCCUPIED: _ClassVar[RunwayOperationalStatus]

class WeatherCondition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WEATHER_CONDITION_UNKNOWN: _ClassVar[WeatherCondition]
    VMC: _ClassVar[WeatherCondition]
    IMC: _ClassVar[WeatherCondition]
    RAIN: _ClassVar[WeatherCondition]
    SNOW: _ClassVar[WeatherCondition]
    FOG: _ClassVar[WeatherCondition]
    THUNDERSTORM: _ClassVar[WeatherCondition]
    WIND_SHEAR: _ClassVar[WeatherCondition]
    ICE: _ClassVar[WeatherCondition]

class HandoffStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HANDOFF_STATUS_UNKNOWN: _ClassVar[HandoffStatus]
    INITIATED: _ClassVar[HandoffStatus]
    ACCEPTED: _ClassVar[HandoffStatus]
    REJECTED: _ClassVar[HandoffStatus]
    HANDOFF_COMPLETED: _ClassVar[HandoffStatus]
    HANDOFF_CANCELLED: _ClassVar[HandoffStatus]

class AlertSeverity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ALERT_SEVERITY_UNKNOWN: _ClassVar[AlertSeverity]
    INFO: _ClassVar[AlertSeverity]
    CAUTION: _ClassVar[AlertSeverity]
    WARNING: _ClassVar[AlertSeverity]
    CRITICAL: _ClassVar[AlertSeverity]

class AlertType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ALERT_TYPE_UNKNOWN: _ClassVar[AlertType]
    EMERGENCY: _ClassVar[AlertType]
    TRAFFIC_CONFLICT: _ClassVar[AlertType]
    WEATHER_HAZARD: _ClassVar[AlertType]
    RUNWAY_INCURSION: _ClassVar[AlertType]
    COMMUNICATION_LOSS: _ClassVar[AlertType]
    SYSTEM_FAILURE: _ClassVar[AlertType]
    UNAUTHORIZED_ENTRY: _ClassVar[AlertType]
    WEATHER_DEVIATION: _ClassVar[AlertType]

class ConvectiveSeverity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONVECTIVE_SEVERITY_UNKNOWN: _ClassVar[ConvectiveSeverity]
    MODERATE: _ClassVar[ConvectiveSeverity]
    SEVERE: _ClassVar[ConvectiveSeverity]
    EXTREME: _ClassVar[ConvectiveSeverity]

class FacilityType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FACILITY_TYPE_UNKNOWN: _ClassVar[FacilityType]
    TOWER: _ClassVar[FacilityType]
    TRACON: _ClassVar[FacilityType]
    CENTER: _ClassVar[FacilityType]
    NATIONAL: _ClassVar[FacilityType]

class GateAssignmentStatusKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GATE_STATUS_UNKNOWN: _ClassVar[GateAssignmentStatusKind]
    PENDING: _ClassVar[GateAssignmentStatusKind]
    ASSIGNED: _ClassVar[GateAssignmentStatusKind]
    GATE_REJECTED: _ClassVar[GateAssignmentStatusKind]
    RELEASED: _ClassVar[GateAssignmentStatusKind]

class NavStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NAV_STATUS_UNKNOWN: _ClassVar[NavStatus]
    NORMAL: _ClassVar[NavStatus]
    NAV_WEATHER_DEVIATION: _ClassVar[NavStatus]
    NAV_HOLDING: _ClassVar[NavStatus]
    NAV_EMERGENCY: _ClassVar[NavStatus]
FLIGHT_PHASE_UNKNOWN: FlightPhase
PREFLIGHT: FlightPhase
TAXI_OUT: FlightPhase
TAKEOFF: FlightPhase
CLIMB: FlightPhase
CRUISE: FlightPhase
DESCENT: FlightPhase
APPROACH: FlightPhase
LANDING: FlightPhase
TAXI_IN: FlightPhase
PARKED: FlightPhase
HOLDING: FlightPhase
INSTRUCTION_TYPE_UNKNOWN: InstructionType
HEADING: InstructionType
ALTITUDE: InstructionType
SPEED: InstructionType
CLEARANCE: InstructionType
HOLD: InstructionType
GO_AROUND: InstructionType
TAXI: InstructionType
PUSHBACK: InstructionType
ACKNOWLEDGMENT_STATUS_UNKNOWN: AcknowledgmentStatus
RECEIVED: AcknowledgmentStatus
WILCO: AcknowledgmentStatus
UNABLE: AcknowledgmentStatus
READBACK_CORRECT: AcknowledgmentStatus
READBACK_INCORRECT: AcknowledgmentStatus
FLIGHT_PLAN_STATUS_UNKNOWN: FlightPlanStatus
FILED: FlightPlanStatus
ACTIVE: FlightPlanStatus
AMENDED: FlightPlanStatus
DELAYED: FlightPlanStatus
CANCELLED: FlightPlanStatus
COMPLETED: FlightPlanStatus
RUNWAY_STATUS_UNKNOWN: RunwayOperationalStatus
OPEN: RunwayOperationalStatus
CLOSED: RunwayOperationalStatus
OCCUPIED: RunwayOperationalStatus
WEATHER_CONDITION_UNKNOWN: WeatherCondition
VMC: WeatherCondition
IMC: WeatherCondition
RAIN: WeatherCondition
SNOW: WeatherCondition
FOG: WeatherCondition
THUNDERSTORM: WeatherCondition
WIND_SHEAR: WeatherCondition
ICE: WeatherCondition
HANDOFF_STATUS_UNKNOWN: HandoffStatus
INITIATED: HandoffStatus
ACCEPTED: HandoffStatus
REJECTED: HandoffStatus
HANDOFF_COMPLETED: HandoffStatus
HANDOFF_CANCELLED: HandoffStatus
ALERT_SEVERITY_UNKNOWN: AlertSeverity
INFO: AlertSeverity
CAUTION: AlertSeverity
WARNING: AlertSeverity
CRITICAL: AlertSeverity
ALERT_TYPE_UNKNOWN: AlertType
EMERGENCY: AlertType
TRAFFIC_CONFLICT: AlertType
WEATHER_HAZARD: AlertType
RUNWAY_INCURSION: AlertType
COMMUNICATION_LOSS: AlertType
SYSTEM_FAILURE: AlertType
UNAUTHORIZED_ENTRY: AlertType
WEATHER_DEVIATION: AlertType
CONVECTIVE_SEVERITY_UNKNOWN: ConvectiveSeverity
MODERATE: ConvectiveSeverity
SEVERE: ConvectiveSeverity
EXTREME: ConvectiveSeverity
FACILITY_TYPE_UNKNOWN: FacilityType
TOWER: FacilityType
TRACON: FacilityType
CENTER: FacilityType
NATIONAL: FacilityType
GATE_STATUS_UNKNOWN: GateAssignmentStatusKind
PENDING: GateAssignmentStatusKind
ASSIGNED: GateAssignmentStatusKind
GATE_REJECTED: GateAssignmentStatusKind
RELEASED: GateAssignmentStatusKind
NAV_STATUS_UNKNOWN: NavStatus
NORMAL: NavStatus
NAV_WEATHER_DEVIATION: NavStatus
NAV_HOLDING: NavStatus
NAV_EMERGENCY: NavStatus

class GeoPosition(_message.Message):
    __slots__ = ("latitude", "longitude", "altitude_feet")
    LATITUDE_FIELD_NUMBER: _ClassVar[int]
    LONGITUDE_FIELD_NUMBER: _ClassVar[int]
    ALTITUDE_FEET_FIELD_NUMBER: _ClassVar[int]
    latitude: float
    longitude: float
    altitude_feet: float
    def __init__(self, latitude: _Optional[float] = ..., longitude: _Optional[float] = ..., altitude_feet: _Optional[float] = ...) -> None: ...

class Wind(_message.Message):
    __slots__ = ("direction_degrees", "speed_knots", "gust_knots")
    DIRECTION_DEGREES_FIELD_NUMBER: _ClassVar[int]
    SPEED_KNOTS_FIELD_NUMBER: _ClassVar[int]
    GUST_KNOTS_FIELD_NUMBER: _ClassVar[int]
    direction_degrees: int
    speed_knots: float
    gust_knots: float
    def __init__(self, direction_degrees: _Optional[int] = ..., speed_knots: _Optional[float] = ..., gust_knots: _Optional[float] = ...) -> None: ...

class Waypoint(_message.Message):
    __slots__ = ("name", "position", "estimated_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    POSITION_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    position: GeoPosition
    estimated_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., position: _Optional[_Union[GeoPosition, _Mapping]] = ..., estimated_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class GateAssignment(_message.Message):
    __slots__ = ("flight_id", "gate_name", "status", "assignment_timestamp", "message")
    FLIGHT_ID_FIELD_NUMBER: _ClassVar[int]
    GATE_NAME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ASSIGNMENT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    flight_id: str
    gate_name: str
    status: GateAssignmentStatusKind
    assignment_timestamp: _timestamp_pb2.Timestamp
    message: str
    def __init__(self, flight_id: _Optional[str] = ..., gate_name: _Optional[str] = ..., status: _Optional[_Union[GateAssignmentStatusKind, str]] = ..., assignment_timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., message: _Optional[str] = ...) -> None: ...

class AircraftPosition(_message.Message):
    __slots__ = ("tail_number", "callsign", "position", "ground_speed_knots", "vertical_speed_fpm", "heading_degrees", "flight_phase", "origin_airport", "destination_airport", "fuel_level_percent", "assigned_runway", "assigned_gate", "nav_status", "timestamp")
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CALLSIGN_FIELD_NUMBER: _ClassVar[int]
    POSITION_FIELD_NUMBER: _ClassVar[int]
    GROUND_SPEED_KNOTS_FIELD_NUMBER: _ClassVar[int]
    VERTICAL_SPEED_FPM_FIELD_NUMBER: _ClassVar[int]
    HEADING_DEGREES_FIELD_NUMBER: _ClassVar[int]
    FLIGHT_PHASE_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_AIRPORT_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_AIRPORT_FIELD_NUMBER: _ClassVar[int]
    FUEL_LEVEL_PERCENT_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_RUNWAY_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_GATE_FIELD_NUMBER: _ClassVar[int]
    NAV_STATUS_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    tail_number: str
    callsign: str
    position: GeoPosition
    ground_speed_knots: float
    vertical_speed_fpm: float
    heading_degrees: float
    flight_phase: FlightPhase
    origin_airport: str
    destination_airport: str
    fuel_level_percent: float
    assigned_runway: str
    assigned_gate: str
    nav_status: NavStatus
    timestamp: _timestamp_pb2.Timestamp
    def __init__(self, tail_number: _Optional[str] = ..., callsign: _Optional[str] = ..., position: _Optional[_Union[GeoPosition, _Mapping]] = ..., ground_speed_knots: _Optional[float] = ..., vertical_speed_fpm: _Optional[float] = ..., heading_degrees: _Optional[float] = ..., flight_phase: _Optional[_Union[FlightPhase, str]] = ..., origin_airport: _Optional[str] = ..., destination_airport: _Optional[str] = ..., fuel_level_percent: _Optional[float] = ..., assigned_runway: _Optional[str] = ..., assigned_gate: _Optional[str] = ..., nav_status: _Optional[_Union[NavStatus, str]] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ControllerInstruction(_message.Message):
    __slots__ = ("instruction_id", "controller_id", "tail_number", "instruction_type", "assigned_heading_degrees", "assigned_altitude_feet", "assigned_speed_knots", "clearance_text", "taxi_route", "hold_reason", "issued_at")
    INSTRUCTION_ID_FIELD_NUMBER: _ClassVar[int]
    CONTROLLER_ID_FIELD_NUMBER: _ClassVar[int]
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    INSTRUCTION_TYPE_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_HEADING_DEGREES_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_ALTITUDE_FEET_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_SPEED_KNOTS_FIELD_NUMBER: _ClassVar[int]
    CLEARANCE_TEXT_FIELD_NUMBER: _ClassVar[int]
    TAXI_ROUTE_FIELD_NUMBER: _ClassVar[int]
    HOLD_REASON_FIELD_NUMBER: _ClassVar[int]
    ISSUED_AT_FIELD_NUMBER: _ClassVar[int]
    instruction_id: str
    controller_id: str
    tail_number: str
    instruction_type: InstructionType
    assigned_heading_degrees: float
    assigned_altitude_feet: int
    assigned_speed_knots: float
    clearance_text: str
    taxi_route: str
    hold_reason: str
    issued_at: _timestamp_pb2.Timestamp
    def __init__(self, instruction_id: _Optional[str] = ..., controller_id: _Optional[str] = ..., tail_number: _Optional[str] = ..., instruction_type: _Optional[_Union[InstructionType, str]] = ..., assigned_heading_degrees: _Optional[float] = ..., assigned_altitude_feet: _Optional[int] = ..., assigned_speed_knots: _Optional[float] = ..., clearance_text: _Optional[str] = ..., taxi_route: _Optional[str] = ..., hold_reason: _Optional[str] = ..., issued_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class PilotAcknowledgment(_message.Message):
    __slots__ = ("acknowledgment_id", "instruction_id", "tail_number", "status", "response_text", "acknowledged_at")
    ACKNOWLEDGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    INSTRUCTION_ID_FIELD_NUMBER: _ClassVar[int]
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_TEXT_FIELD_NUMBER: _ClassVar[int]
    ACKNOWLEDGED_AT_FIELD_NUMBER: _ClassVar[int]
    acknowledgment_id: str
    instruction_id: str
    tail_number: str
    status: AcknowledgmentStatus
    response_text: str
    acknowledged_at: _timestamp_pb2.Timestamp
    def __init__(self, acknowledgment_id: _Optional[str] = ..., instruction_id: _Optional[str] = ..., tail_number: _Optional[str] = ..., status: _Optional[_Union[AcknowledgmentStatus, str]] = ..., response_text: _Optional[str] = ..., acknowledged_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class FlightPlan(_message.Message):
    __slots__ = ("flight_plan_id", "tail_number", "callsign", "departure_airport", "arrival_airport", "waypoints", "scheduled_departure_time", "estimated_departure_time", "scheduled_arrival_time", "estimated_arrival_time", "status", "last_updated")
    FLIGHT_PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CALLSIGN_FIELD_NUMBER: _ClassVar[int]
    DEPARTURE_AIRPORT_FIELD_NUMBER: _ClassVar[int]
    ARRIVAL_AIRPORT_FIELD_NUMBER: _ClassVar[int]
    WAYPOINTS_FIELD_NUMBER: _ClassVar[int]
    SCHEDULED_DEPARTURE_TIME_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_DEPARTURE_TIME_FIELD_NUMBER: _ClassVar[int]
    SCHEDULED_ARRIVAL_TIME_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_ARRIVAL_TIME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LAST_UPDATED_FIELD_NUMBER: _ClassVar[int]
    flight_plan_id: str
    tail_number: str
    callsign: str
    departure_airport: str
    arrival_airport: str
    waypoints: _containers.RepeatedCompositeFieldContainer[Waypoint]
    scheduled_departure_time: _timestamp_pb2.Timestamp
    estimated_departure_time: _timestamp_pb2.Timestamp
    scheduled_arrival_time: _timestamp_pb2.Timestamp
    estimated_arrival_time: _timestamp_pb2.Timestamp
    status: FlightPlanStatus
    last_updated: _timestamp_pb2.Timestamp
    def __init__(self, flight_plan_id: _Optional[str] = ..., tail_number: _Optional[str] = ..., callsign: _Optional[str] = ..., departure_airport: _Optional[str] = ..., arrival_airport: _Optional[str] = ..., waypoints: _Optional[_Iterable[_Union[Waypoint, _Mapping]]] = ..., scheduled_departure_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., estimated_departure_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., scheduled_arrival_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., estimated_arrival_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., status: _Optional[_Union[FlightPlanStatus, str]] = ..., last_updated: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class RunwayStatus(_message.Message):
    __slots__ = ("airport_code", "runway_id", "status", "remarks", "timestamp")
    AIRPORT_CODE_FIELD_NUMBER: _ClassVar[int]
    RUNWAY_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REMARKS_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    airport_code: str
    runway_id: str
    status: RunwayOperationalStatus
    remarks: str
    timestamp: _timestamp_pb2.Timestamp
    def __init__(self, airport_code: _Optional[str] = ..., runway_id: _Optional[str] = ..., status: _Optional[_Union[RunwayOperationalStatus, str]] = ..., remarks: _Optional[str] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class WeatherReport(_message.Message):
    __slots__ = ("airport_code", "wind", "visibility_meters", "ceiling_feet", "temperature_celsius", "altimeter_hpa", "conditions", "observation_time")
    AIRPORT_CODE_FIELD_NUMBER: _ClassVar[int]
    WIND_FIELD_NUMBER: _ClassVar[int]
    VISIBILITY_METERS_FIELD_NUMBER: _ClassVar[int]
    CEILING_FEET_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_CELSIUS_FIELD_NUMBER: _ClassVar[int]
    ALTIMETER_HPA_FIELD_NUMBER: _ClassVar[int]
    CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_TIME_FIELD_NUMBER: _ClassVar[int]
    airport_code: str
    wind: Wind
    visibility_meters: float
    ceiling_feet: int
    temperature_celsius: float
    altimeter_hpa: float
    conditions: WeatherCondition
    observation_time: _timestamp_pb2.Timestamp
    def __init__(self, airport_code: _Optional[str] = ..., wind: _Optional[_Union[Wind, _Mapping]] = ..., visibility_meters: _Optional[float] = ..., ceiling_feet: _Optional[int] = ..., temperature_celsius: _Optional[float] = ..., altimeter_hpa: _Optional[float] = ..., conditions: _Optional[_Union[WeatherCondition, str]] = ..., observation_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Handoff(_message.Message):
    __slots__ = ("handoff_id", "tail_number", "from_controller_id", "to_controller_id", "status", "from_facility_type", "to_facility_type", "sector", "frequency", "initiated_at", "completed_at")
    HANDOFF_ID_FIELD_NUMBER: _ClassVar[int]
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    FROM_CONTROLLER_ID_FIELD_NUMBER: _ClassVar[int]
    TO_CONTROLLER_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    FROM_FACILITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    TO_FACILITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    SECTOR_FIELD_NUMBER: _ClassVar[int]
    FREQUENCY_FIELD_NUMBER: _ClassVar[int]
    INITIATED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    handoff_id: str
    tail_number: str
    from_controller_id: str
    to_controller_id: str
    status: HandoffStatus
    from_facility_type: FacilityType
    to_facility_type: FacilityType
    sector: str
    frequency: str
    initiated_at: _timestamp_pb2.Timestamp
    completed_at: _timestamp_pb2.Timestamp
    def __init__(self, handoff_id: _Optional[str] = ..., tail_number: _Optional[str] = ..., from_controller_id: _Optional[str] = ..., to_controller_id: _Optional[str] = ..., status: _Optional[_Union[HandoffStatus, str]] = ..., from_facility_type: _Optional[_Union[FacilityType, str]] = ..., to_facility_type: _Optional[_Union[FacilityType, str]] = ..., sector: _Optional[str] = ..., frequency: _Optional[str] = ..., initiated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Alert(_message.Message):
    __slots__ = ("alert_id", "alert_type", "severity", "involved_aircraft", "airport_code", "runway_id", "message", "timestamp")
    ALERT_ID_FIELD_NUMBER: _ClassVar[int]
    ALERT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    INVOLVED_AIRCRAFT_FIELD_NUMBER: _ClassVar[int]
    AIRPORT_CODE_FIELD_NUMBER: _ClassVar[int]
    RUNWAY_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    involved_aircraft: _containers.RepeatedScalarFieldContainer[str]
    airport_code: str
    runway_id: str
    message: str
    timestamp: _timestamp_pb2.Timestamp
    def __init__(self, alert_id: _Optional[str] = ..., alert_type: _Optional[_Union[AlertType, str]] = ..., severity: _Optional[_Union[AlertSeverity, str]] = ..., involved_aircraft: _Optional[_Iterable[str]] = ..., airport_code: _Optional[str] = ..., runway_id: _Optional[str] = ..., message: _Optional[str] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class AircraftTracking(_message.Message):
    __slots__ = ("tail_number", "controller_id", "facility_id", "facility_type", "acquired_at")
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CONTROLLER_ID_FIELD_NUMBER: _ClassVar[int]
    FACILITY_ID_FIELD_NUMBER: _ClassVar[int]
    FACILITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACQUIRED_AT_FIELD_NUMBER: _ClassVar[int]
    tail_number: str
    controller_id: str
    facility_id: str
    facility_type: FacilityType
    acquired_at: _timestamp_pb2.Timestamp
    def __init__(self, tail_number: _Optional[str] = ..., controller_id: _Optional[str] = ..., facility_id: _Optional[str] = ..., facility_type: _Optional[_Union[FacilityType, str]] = ..., acquired_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class FacilityStatus(_message.Message):
    __slots__ = ("facility_id", "facility_type", "controller_id", "tracked_aircraft_count", "last_updated")
    FACILITY_ID_FIELD_NUMBER: _ClassVar[int]
    FACILITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTROLLER_ID_FIELD_NUMBER: _ClassVar[int]
    TRACKED_AIRCRAFT_COUNT_FIELD_NUMBER: _ClassVar[int]
    LAST_UPDATED_FIELD_NUMBER: _ClassVar[int]
    facility_id: str
    facility_type: FacilityType
    controller_id: str
    tracked_aircraft_count: int
    last_updated: _timestamp_pb2.Timestamp
    def __init__(self, facility_id: _Optional[str] = ..., facility_type: _Optional[_Union[FacilityType, str]] = ..., controller_id: _Optional[str] = ..., tracked_aircraft_count: _Optional[int] = ..., last_updated: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ConvectiveCell(_message.Message):
    __slots__ = ("cell_id", "center_latitude", "center_longitude", "radius_nm", "top_altitude_ft", "base_altitude_ft", "severity", "movement_heading_deg", "movement_speed_knots", "observation_time")
    CELL_ID_FIELD_NUMBER: _ClassVar[int]
    CENTER_LATITUDE_FIELD_NUMBER: _ClassVar[int]
    CENTER_LONGITUDE_FIELD_NUMBER: _ClassVar[int]
    RADIUS_NM_FIELD_NUMBER: _ClassVar[int]
    TOP_ALTITUDE_FT_FIELD_NUMBER: _ClassVar[int]
    BASE_ALTITUDE_FT_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    MOVEMENT_HEADING_DEG_FIELD_NUMBER: _ClassVar[int]
    MOVEMENT_SPEED_KNOTS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_TIME_FIELD_NUMBER: _ClassVar[int]
    cell_id: str
    center_latitude: float
    center_longitude: float
    radius_nm: float
    top_altitude_ft: int
    base_altitude_ft: int
    severity: ConvectiveSeverity
    movement_heading_deg: float
    movement_speed_knots: float
    observation_time: _timestamp_pb2.Timestamp
    def __init__(self, cell_id: _Optional[str] = ..., center_latitude: _Optional[float] = ..., center_longitude: _Optional[float] = ..., radius_nm: _Optional[float] = ..., top_altitude_ft: _Optional[int] = ..., base_altitude_ft: _Optional[int] = ..., severity: _Optional[_Union[ConvectiveSeverity, str]] = ..., movement_heading_deg: _Optional[float] = ..., movement_speed_knots: _Optional[float] = ..., observation_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class FlightPlanRequest(_message.Message):
    __slots__ = ("plan",)
    PLAN_FIELD_NUMBER: _ClassVar[int]
    plan: FlightPlan
    def __init__(self, plan: _Optional[_Union[FlightPlan, _Mapping]] = ...) -> None: ...

class FlightPlanResponse(_message.Message):
    __slots__ = ("flight_plan_id", "accepted", "message", "response_timestamp")
    FLIGHT_PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    flight_plan_id: str
    accepted: bool
    message: str
    response_timestamp: _timestamp_pb2.Timestamp
    def __init__(self, flight_plan_id: _Optional[str] = ..., accepted: bool = ..., message: _Optional[str] = ..., response_timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class GateRequest(_message.Message):
    __slots__ = ("flight_id", "aerodrome_id", "requested_timestamp", "requires_assignment")
    FLIGHT_ID_FIELD_NUMBER: _ClassVar[int]
    AERODROME_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    REQUIRES_ASSIGNMENT_FIELD_NUMBER: _ClassVar[int]
    flight_id: str
    aerodrome_id: str
    requested_timestamp: _timestamp_pb2.Timestamp
    requires_assignment: bool
    def __init__(self, flight_id: _Optional[str] = ..., aerodrome_id: _Optional[str] = ..., requested_timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., requires_assignment: bool = ...) -> None: ...

class GateAssignmentReply(_message.Message):
    __slots__ = ("flight_id", "assignment")
    FLIGHT_ID_FIELD_NUMBER: _ClassVar[int]
    ASSIGNMENT_FIELD_NUMBER: _ClassVar[int]
    flight_id: str
    assignment: GateAssignment
    def __init__(self, flight_id: _Optional[str] = ..., assignment: _Optional[_Union[GateAssignment, _Mapping]] = ...) -> None: ...

class ControllerInstructionFilter(_message.Message):
    __slots__ = ("tail_number",)
    TAIL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    tail_number: str
    def __init__(self, tail_number: _Optional[str] = ...) -> None: ...

class WeatherReportFilter(_message.Message):
    __slots__ = ("airport_code",)
    AIRPORT_CODE_FIELD_NUMBER: _ClassVar[int]
    airport_code: str
    def __init__(self, airport_code: _Optional[str] = ...) -> None: ...

class HandoffFilter(_message.Message):
    __slots__ = ("controller_id",)
    CONTROLLER_ID_FIELD_NUMBER: _ClassVar[int]
    controller_id: str
    def __init__(self, controller_id: _Optional[str] = ...) -> None: ...

class EmptyFilter(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HandoffAck(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class CellInjectionAck(_message.Message):
    __slots__ = ("accepted", "cell_id")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    CELL_ID_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    cell_id: str
    def __init__(self, accepted: bool = ..., cell_id: _Optional[str] = ...) -> None: ...
