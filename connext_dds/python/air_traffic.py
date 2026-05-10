
# WARNING: THIS FILE IS AUTO-GENERATED. DO NOT MODIFY.

# This file was generated from air_traffic.idl
# using RTI Code Generator (rtiddsgen) version 4.7.0.
# The rtiddsgen tool is part of the RTI Connext DDS distribution.
# For more information, type 'rtiddsgen -help' at a command shell
# or consult the Code Generator User's Manual.

from dataclasses import field
from typing import Union, Sequence, Optional
import rti.idl as idl
import rti.rpc as rpc
from enum import IntEnum
import sys
import os
from abc import ABC



NationalAirTrafficControl = idl.get_module("NationalAirTrafficControl")

NationalAirTrafficControl_MAX_ID_LEN = 64

NationalAirTrafficControl.MAX_ID_LEN = NationalAirTrafficControl_MAX_ID_LEN

NationalAirTrafficControl_MAX_TAIL_NUMBER_LEN = 16

NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN = NationalAirTrafficControl_MAX_TAIL_NUMBER_LEN

NationalAirTrafficControl_MAX_CONTROLLER_ID_LEN = 32

NationalAirTrafficControl.MAX_CONTROLLER_ID_LEN = NationalAirTrafficControl_MAX_CONTROLLER_ID_LEN

NationalAirTrafficControl_MAX_INSTRUCTION_ID_LEN = 64

NationalAirTrafficControl.MAX_INSTRUCTION_ID_LEN = NationalAirTrafficControl_MAX_INSTRUCTION_ID_LEN

NationalAirTrafficControl_MAX_CALLSIGN_LEN = 16

NationalAirTrafficControl.MAX_CALLSIGN_LEN = NationalAirTrafficControl_MAX_CALLSIGN_LEN

NationalAirTrafficControl_MAX_AIRPORT_CODE_LEN = 8

NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN = NationalAirTrafficControl_MAX_AIRPORT_CODE_LEN

NationalAirTrafficControl_MAX_RUNWAY_ID_LEN = 16

NationalAirTrafficControl.MAX_RUNWAY_ID_LEN = NationalAirTrafficControl_MAX_RUNWAY_ID_LEN

NationalAirTrafficControl_MAX_WAYPOINT_NAME_LEN = 16

NationalAirTrafficControl.MAX_WAYPOINT_NAME_LEN = NationalAirTrafficControl_MAX_WAYPOINT_NAME_LEN

NationalAirTrafficControl_MAX_TEXT_LEN = 256

NationalAirTrafficControl.MAX_TEXT_LEN = NationalAirTrafficControl_MAX_TEXT_LEN

NationalAirTrafficControl_MAX_ROUTE_POINTS = 128

NationalAirTrafficControl.MAX_ROUTE_POINTS = NationalAirTrafficControl_MAX_ROUTE_POINTS

NationalAirTrafficControl_MAX_INVOLVED_AIRCRAFT = 16

NationalAirTrafficControl.MAX_INVOLVED_AIRCRAFT = NationalAirTrafficControl_MAX_INVOLVED_AIRCRAFT

NationalAirTrafficControl_IdString = str

NationalAirTrafficControl.IdString = NationalAirTrafficControl_IdString

NationalAirTrafficControl_TailNumber = str

NationalAirTrafficControl.TailNumber = NationalAirTrafficControl_TailNumber

NationalAirTrafficControl_ControllerId = str

NationalAirTrafficControl.ControllerId = NationalAirTrafficControl_ControllerId

NationalAirTrafficControl_InstructionId = str

NationalAirTrafficControl.InstructionId = NationalAirTrafficControl_InstructionId

NationalAirTrafficControl_Callsign = str

NationalAirTrafficControl.Callsign = NationalAirTrafficControl_Callsign

NationalAirTrafficControl_AirportCode = str

NationalAirTrafficControl.AirportCode = NationalAirTrafficControl_AirportCode

NationalAirTrafficControl_RunwayId = str

NationalAirTrafficControl.RunwayId = NationalAirTrafficControl_RunwayId

NationalAirTrafficControl_WaypointName = str

NationalAirTrafficControl.WaypointName = NationalAirTrafficControl_WaypointName

NationalAirTrafficControl_ShortText = str

NationalAirTrafficControl.ShortText = NationalAirTrafficControl_ShortText

NationalAirTrafficControl_Timestamp = int

NationalAirTrafficControl.Timestamp = NationalAirTrafficControl_Timestamp

@idl.struct(
    type_annotations = [idl.type_name("NationalAirTrafficControl::GeoPosition"), ])
class NationalAirTrafficControl_GeoPosition:
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_feet: float = 0.0

NationalAirTrafficControl.GeoPosition = NationalAirTrafficControl_GeoPosition

@idl.struct(
    type_annotations = [idl.type_name("NationalAirTrafficControl::Wind"), ])
class NationalAirTrafficControl_Wind:
    direction_degrees: idl.uint16 = 0
    speed_knots: idl.float32 = 0.0
    gust_knots: Optional[idl.float32] = None

NationalAirTrafficControl.Wind = NationalAirTrafficControl_Wind

@idl.struct(
    type_annotations = [idl.type_name("NationalAirTrafficControl::Waypoint"), ],

    member_annotations = {
        'name': [idl.bound(NationalAirTrafficControl.MAX_WAYPOINT_NAME_LEN),],
    }
)
class NationalAirTrafficControl_Waypoint:
    name: str = ""
    position: NationalAirTrafficControl.GeoPosition = field(default_factory = NationalAirTrafficControl.GeoPosition)
    estimated_time: Optional[int] = None

NationalAirTrafficControl.Waypoint = NationalAirTrafficControl_Waypoint

@idl.enum
class NationalAirTrafficControl_FlightPhase(IntEnum):
    PREFLIGHT = 0
    TAXI_OUT = 1
    TAKEOFF = 2
    CLIMB = 3
    CRUISE = 4
    DESCENT = 5
    APPROACH = 6
    LANDING = 7
    TAXI_IN = 8
    PARKED = 9
    HOLDING = 10

NationalAirTrafficControl.FlightPhase = NationalAirTrafficControl_FlightPhase

@idl.enum
class NationalAirTrafficControl_InstructionType(IntEnum):
    HEADING = 0
    ALTITUDE = 1
    SPEED = 2
    CLEARANCE = 3
    HOLD = 4
    GO_AROUND = 5
    TAXI = 6
    PUSHBACK = 7

NationalAirTrafficControl.InstructionType = NationalAirTrafficControl_InstructionType

@idl.enum
class NationalAirTrafficControl_AcknowledgmentStatus(IntEnum):
    RECEIVED = 0
    WILCO = 1
    UNABLE = 2
    READBACK_CORRECT = 3
    READBACK_INCORRECT = 4

NationalAirTrafficControl.AcknowledgmentStatus = NationalAirTrafficControl_AcknowledgmentStatus

@idl.enum
class NationalAirTrafficControl_FlightPlanStatus(IntEnum):
    FILED = 0
    ACTIVE = 1
    AMENDED = 2
    DELAYED = 3
    CANCELLED = 4
    COMPLETED = 5

NationalAirTrafficControl.FlightPlanStatus = NationalAirTrafficControl_FlightPlanStatus

@idl.enum
class NationalAirTrafficControl_RunwayOperationalStatus(IntEnum):
    OPEN = 0
    CLOSED = 1
    OCCUPIED = 2

NationalAirTrafficControl.RunwayOperationalStatus = NationalAirTrafficControl_RunwayOperationalStatus

@idl.enum
class NationalAirTrafficControl_WeatherCondition(IntEnum):
    VMC = 0
    IMC = 1
    RAIN = 2
    SNOW = 3
    FOG = 4
    THUNDERSTORM = 5
    WIND_SHEAR = 6
    ICE = 7

NationalAirTrafficControl.WeatherCondition = NationalAirTrafficControl_WeatherCondition

@idl.enum
class NationalAirTrafficControl_HandoffStatus(IntEnum):
    INITIATED = 0
    ACCEPTED = 1
    REJECTED = 2
    COMPLETED = 3
    CANCELLED = 4

NationalAirTrafficControl.HandoffStatus = NationalAirTrafficControl_HandoffStatus

@idl.enum
class NationalAirTrafficControl_AlertSeverity(IntEnum):
    INFO = 0
    CAUTION = 1
    WARNING = 2
    CRITICAL = 3

NationalAirTrafficControl.AlertSeverity = NationalAirTrafficControl_AlertSeverity

@idl.enum
class NationalAirTrafficControl_AlertType(IntEnum):
    EMERGENCY = 0
    TRAFFIC_CONFLICT = 1
    WEATHER_HAZARD = 2
    RUNWAY_INCURSION = 3
    COMMUNICATION_LOSS = 4
    SYSTEM_FAILURE = 5
    UNAUTHORIZED_ENTRY = 6
    WEATHER_DEVIATION = 7

NationalAirTrafficControl.AlertType = NationalAirTrafficControl_AlertType

@idl.enum
class NationalAirTrafficControl_ConvectiveSeverity(IntEnum):
    MODERATE = 0
    SEVERE = 1
    EXTREME = 2

NationalAirTrafficControl.ConvectiveSeverity = NationalAirTrafficControl_ConvectiveSeverity

@idl.enum
class NationalAirTrafficControl_FacilityType(IntEnum):
    TOWER = 0
    TRACON = 1
    CENTER = 2
    NATIONAL = 3

NationalAirTrafficControl.FacilityType = NationalAirTrafficControl_FacilityType

@idl.enum
class NationalAirTrafficControl_GateAssignmentStatusKind(IntEnum):
    PENDING = 0
    ASSIGNED = 1
    REJECTED = 2
    RELEASED = 3

NationalAirTrafficControl.GateAssignmentStatusKind = NationalAirTrafficControl_GateAssignmentStatusKind

@idl.enum
class NationalAirTrafficControl_NavStatus(IntEnum):
    NORMAL = 0
    WEATHER_DEVIATION = 1
    HOLDING = 2
    EMERGENCY = 3

NationalAirTrafficControl.NavStatus = NationalAirTrafficControl_NavStatus

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::AircraftPosition"), ],

    member_annotations = {
        'tail_number': [idl.key, idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'callsign': [idl.bound(NationalAirTrafficControl.MAX_CALLSIGN_LEN),],
        'flight_phase': [idl.default(0),],
        'origin_airport': [idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'destination_airport': [idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'assigned_runway': [idl.bound(NationalAirTrafficControl.MAX_RUNWAY_ID_LEN),],
        'nav_status': [idl.default(0),],
    }
)
class NationalAirTrafficControl_AircraftPosition:
    tail_number: str = ""
    callsign: str = ""
    position: NationalAirTrafficControl.GeoPosition = field(default_factory = NationalAirTrafficControl.GeoPosition)
    ground_speed_knots: idl.float32 = 0.0
    vertical_speed_fpm: idl.float32 = 0.0
    heading_degrees: idl.float32 = 0.0
    flight_phase: NationalAirTrafficControl.FlightPhase = NationalAirTrafficControl.FlightPhase.PREFLIGHT
    origin_airport: str = ""
    destination_airport: str = ""
    fuel_level_percent: idl.float32 = 0.0
    assigned_runway: Optional[str] = None
    nav_status: Optional[NationalAirTrafficControl.NavStatus] = None
    timestamp: int = 0

NationalAirTrafficControl.AircraftPosition = NationalAirTrafficControl_AircraftPosition

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::ControllerInstruction"), ],

    member_annotations = {
        'instruction_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_INSTRUCTION_ID_LEN),],
        'controller_id': [idl.bound(NationalAirTrafficControl.MAX_CONTROLLER_ID_LEN),],
        'tail_number': [idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'instruction_type': [idl.default(0),],
        'clearance_text': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
        'taxi_route': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
        'hold_reason': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_ControllerInstruction:
    instruction_id: str = ""
    controller_id: str = ""
    tail_number: str = ""
    instruction_type: NationalAirTrafficControl.InstructionType = NationalAirTrafficControl.InstructionType.HEADING
    assigned_heading_degrees: Optional[idl.float32] = None
    assigned_altitude_feet: Optional[idl.int32] = None
    assigned_speed_knots: Optional[idl.float32] = None
    clearance_text: Optional[str] = None
    taxi_route: Optional[str] = None
    hold_reason: Optional[str] = None
    issued_at: int = 0

NationalAirTrafficControl.ControllerInstruction = NationalAirTrafficControl_ControllerInstruction

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::PilotAcknowledgment"), ],

    member_annotations = {
        'acknowledgment_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_ID_LEN),],
        'instruction_id': [idl.bound(NationalAirTrafficControl.MAX_INSTRUCTION_ID_LEN),],
        'tail_number': [idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'status': [idl.default(0),],
        'response_text': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_PilotAcknowledgment:
    acknowledgment_id: str = ""
    instruction_id: str = ""
    tail_number: str = ""
    status: NationalAirTrafficControl.AcknowledgmentStatus = NationalAirTrafficControl.AcknowledgmentStatus.RECEIVED
    response_text: Optional[str] = None
    acknowledged_at: int = 0

NationalAirTrafficControl.PilotAcknowledgment = NationalAirTrafficControl_PilotAcknowledgment

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::FlightPlan"), ],

    member_annotations = {
        'flight_plan_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_ID_LEN),],
        'tail_number': [idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'callsign': [idl.bound(NationalAirTrafficControl.MAX_CALLSIGN_LEN),],
        'departure_airport': [idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'arrival_airport': [idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'waypoints': [idl.bound(NationalAirTrafficControl.MAX_ROUTE_POINTS),],
        'status': [idl.default(0),],
    }
)
class NationalAirTrafficControl_FlightPlan:
    flight_plan_id: str = ""
    tail_number: str = ""
    callsign: str = ""
    departure_airport: str = ""
    arrival_airport: str = ""
    waypoints: Sequence[NationalAirTrafficControl.Waypoint] = field(default_factory = list)
    scheduled_departure_time: int = 0
    estimated_departure_time: Optional[int] = None
    scheduled_arrival_time: Optional[int] = None
    estimated_arrival_time: Optional[int] = None
    status: NationalAirTrafficControl.FlightPlanStatus = NationalAirTrafficControl.FlightPlanStatus.FILED
    last_updated: int = 0

NationalAirTrafficControl.FlightPlan = NationalAirTrafficControl_FlightPlan

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::RunwayStatus"), ],

    member_annotations = {
        'airport_code': [idl.key, idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'runway_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_RUNWAY_ID_LEN),],
        'status': [idl.default(0),],
        'remarks': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_RunwayStatus:
    airport_code: str = ""
    runway_id: str = ""
    status: NationalAirTrafficControl.RunwayOperationalStatus = NationalAirTrafficControl.RunwayOperationalStatus.OPEN
    remarks: Optional[str] = None
    timestamp: int = 0

NationalAirTrafficControl.RunwayStatus = NationalAirTrafficControl_RunwayStatus

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::WeatherReport"), ],

    member_annotations = {
        'airport_code': [idl.key, idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'conditions': [idl.default(0),],
    }
)
class NationalAirTrafficControl_WeatherReport:
    airport_code: str = ""
    wind: NationalAirTrafficControl.Wind = field(default_factory = NationalAirTrafficControl.Wind)
    visibility_meters: idl.float32 = 0.0
    ceiling_feet: idl.int32 = 0
    temperature_celsius: idl.float32 = 0.0
    altimeter_hpa: idl.float32 = 0.0
    conditions: NationalAirTrafficControl.WeatherCondition = NationalAirTrafficControl.WeatherCondition.VMC
    observation_time: int = 0

NationalAirTrafficControl.WeatherReport = NationalAirTrafficControl_WeatherReport

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::Handoff"), ],

    member_annotations = {
        'handoff_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_ID_LEN),],
        'tail_number': [idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'from_controller_id': [idl.bound(NationalAirTrafficControl.MAX_CONTROLLER_ID_LEN),],
        'to_controller_id': [idl.bound(NationalAirTrafficControl.MAX_CONTROLLER_ID_LEN),],
        'status': [idl.default(0),],
        'from_facility_type': [idl.default(0),],
        'to_facility_type': [idl.default(0),],
        'sector': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
        'frequency': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_Handoff:
    handoff_id: str = ""
    tail_number: str = ""
    from_controller_id: str = ""
    to_controller_id: str = ""
    status: NationalAirTrafficControl.HandoffStatus = NationalAirTrafficControl.HandoffStatus.INITIATED
    from_facility_type: Optional[NationalAirTrafficControl.FacilityType] = None
    to_facility_type: Optional[NationalAirTrafficControl.FacilityType] = None
    sector: Optional[str] = None
    frequency: Optional[str] = None
    initiated_at: int = 0
    completed_at: Optional[int] = None

NationalAirTrafficControl.Handoff = NationalAirTrafficControl_Handoff

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::Alert"), ],

    member_annotations = {
        'alert_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_ID_LEN),],
        'alert_type': [idl.default(0),],
        'severity': [idl.default(0),],
        'involved_aircraft': [idl.bound(NationalAirTrafficControl.MAX_INVOLVED_AIRCRAFT), idl.element_annotations([idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN)]),],
        'airport_code': [idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
        'runway_id': [idl.bound(NationalAirTrafficControl.MAX_RUNWAY_ID_LEN),],
        'message': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_Alert:
    alert_id: str = ""
    alert_type: NationalAirTrafficControl.AlertType = NationalAirTrafficControl.AlertType.EMERGENCY
    severity: NationalAirTrafficControl.AlertSeverity = NationalAirTrafficControl.AlertSeverity.INFO
    involved_aircraft: Sequence[str] = field(default_factory = list)
    airport_code: Optional[str] = None
    runway_id: Optional[str] = None
    message: str = ""
    timestamp: int = 0

NationalAirTrafficControl.Alert = NationalAirTrafficControl_Alert

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::AircraftTracking"), ],

    member_annotations = {
        'tail_number': [idl.key, idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'controller_id': [idl.bound(NationalAirTrafficControl.MAX_CONTROLLER_ID_LEN),],
        'facility_id': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
        'facility_type': [idl.default(0),],
    }
)
class NationalAirTrafficControl_AircraftTracking:
    tail_number: str = ""
    controller_id: str = ""
    facility_id: str = ""
    facility_type: NationalAirTrafficControl.FacilityType = NationalAirTrafficControl.FacilityType.TOWER
    acquired_at: int = 0

NationalAirTrafficControl.AircraftTracking = NationalAirTrafficControl_AircraftTracking

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::FacilityStatus"), ],

    member_annotations = {
        'facility_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
        'facility_type': [idl.default(0),],
        'controller_id': [idl.bound(NationalAirTrafficControl.MAX_CONTROLLER_ID_LEN),],
    }
)
class NationalAirTrafficControl_FacilityStatus:
    facility_id: str = ""
    facility_type: NationalAirTrafficControl.FacilityType = NationalAirTrafficControl.FacilityType.TOWER
    controller_id: str = ""
    tracked_aircraft_count: idl.uint32 = 0
    last_updated: int = 0

NationalAirTrafficControl.FacilityStatus = NationalAirTrafficControl_FacilityStatus

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::ConvectiveCell"), ],

    member_annotations = {
        'cell_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_ID_LEN),],
        'severity': [idl.default(0),],
    }
)
class NationalAirTrafficControl_ConvectiveCell:
    cell_id: str = ""
    center_latitude: float = 0.0
    center_longitude: float = 0.0
    radius_nm: float = 0.0
    top_altitude_ft: idl.int32 = 0
    base_altitude_ft: idl.int32 = 0
    severity: NationalAirTrafficControl.ConvectiveSeverity = NationalAirTrafficControl.ConvectiveSeverity.MODERATE
    movement_heading_deg: idl.float32 = 0.0
    movement_speed_knots: idl.float32 = 0.0
    observation_time: int = 0

NationalAirTrafficControl.ConvectiveCell = NationalAirTrafficControl_ConvectiveCell

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::FlightPlanRequest"), ])
class NationalAirTrafficControl_FlightPlanRequest:
    plan: NationalAirTrafficControl.FlightPlan = field(default_factory = NationalAirTrafficControl.FlightPlan)

NationalAirTrafficControl.FlightPlanRequest = NationalAirTrafficControl_FlightPlanRequest

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::FlightPlanResponse"), ],

    member_annotations = {
        'flight_plan_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_ID_LEN),],
        'message': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_FlightPlanResponse:
    flight_plan_id: str = ""
    accepted: bool = False
    message: Optional[str] = None
    response_timestamp: int = 0

NationalAirTrafficControl.FlightPlanResponse = NationalAirTrafficControl_FlightPlanResponse

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::GateRequest"), ],

    member_annotations = {
        'flight_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'aerodrome_id': [idl.bound(NationalAirTrafficControl.MAX_AIRPORT_CODE_LEN),],
    }
)
class NationalAirTrafficControl_GateRequest:
    flight_id: str = ""
    aerodrome_id: str = ""
    requested_timestamp: int = 0
    requires_assignment: bool = False

NationalAirTrafficControl.GateRequest = NationalAirTrafficControl_GateRequest

@idl.struct(
    type_annotations = [idl.type_name("NationalAirTrafficControl::GateAssignment"), ],

    member_annotations = {
        'flight_id': [idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
        'gate_name': [idl.bound(16),],
        'status': [idl.default(0),],
        'message': [idl.bound(NationalAirTrafficControl.MAX_TEXT_LEN),],
    }
)
class NationalAirTrafficControl_GateAssignment:
    flight_id: str = ""
    gate_name: str = ""
    status: NationalAirTrafficControl.GateAssignmentStatusKind = NationalAirTrafficControl.GateAssignmentStatusKind.PENDING
    assignment_timestamp: int = 0
    message: Optional[str] = None

NationalAirTrafficControl.GateAssignment = NationalAirTrafficControl_GateAssignment

@idl.struct(
    type_annotations = [idl.mutable, idl.type_name("NationalAirTrafficControl::GateAssignmentReply"), ],

    member_annotations = {
        'flight_id': [idl.key, idl.bound(NationalAirTrafficControl.MAX_TAIL_NUMBER_LEN),],
    }
)
class NationalAirTrafficControl_GateAssignmentReply:
    flight_id: str = ""
    assignment: NationalAirTrafficControl.GateAssignment = field(default_factory = NationalAirTrafficControl.GateAssignment)

NationalAirTrafficControl.GateAssignmentReply = NationalAirTrafficControl_GateAssignmentReply
