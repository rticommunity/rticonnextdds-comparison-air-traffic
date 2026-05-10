User: How are the DDS domain participants configured to find the RTI Collector Service?

GitHub Copilot: Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/scripts/run_collector.sh)

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/qos/USER_QOS_PROFILES.xml#1-1), lines 1 to 150

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/config/scenario_default.json#1-1), lines 1 to 80

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/qos/USER_QOS_PROFILES.xml#150-150), lines 150 to 300

Searched for regex `discovery|initial_peers|collector` (`**/*.xml`), 8 results

Searched for regex `collector|monitoring|observ` (`**/*.py`), 8 results

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/gateway_1.xml#1-1), lines 1 to 80

Searched for regex `monitoring_topic_prefix|monitoring|enable_topic_discovery` (`**/*.py`), 2 results

Searched for regex `DomainParticipant|participant_qos|QosProvider` (`**/*.py`), 20 results

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/common/__init__.py#155-155), lines 155 to 215

Read [](file:///Users/gerardo/dom/gitrepos/rticonnextdds-comparison-air-traffic/connext_dds/src/common/__init__.py#1-1), lines 1 to 155

The domain participants in this project discover the RTI Collector Service through **standard DDS multicast-based discovery on the LAN** — no explicit `initial_peers` configuration is needed. Here's how it works:

1. **All apps join domain 0** (common/\_\_init\_\_.py: `DOMAIN_ID = 0`) and use the `AtcParticipantProfile` QoS, which inherits from `BuiltinQosLib::Generic.Common` with fast discovery optimizations.

2. **Transport is UDPv4 only** (common/\_\_init\_\_.py):
   ```python
   participant_qos.transport_builtin.mask = dds.TransportBuiltinMask.UDPv4
   ```

3. **No explicit `initial_peers`** are set in the Python apps — they rely on the default multicast peer (`239.255.0.1`) for domain 0.

4. **The Collector Service** is launched with a built-in configuration (run_collector.sh):
   ```bash
   ${NDDSHOME}/bin/rticollectorservicelite -cfgName NonSecureRemoteDebuggingLAN
   ```
   This built-in `NonSecureRemoteDebuggingLAN` configuration also joins domain 0 on the LAN using default discovery peers.

**In summary:** Both the application participants and the Collector Service use the same domain (0) and the same default UDPv4 multicast discovery mechanism — they find each other automatically via the standard SPDP multicast address without any explicit peer list configuration. The Collector then exposes its data on `ws://localhost:19098` for external observability tools.
