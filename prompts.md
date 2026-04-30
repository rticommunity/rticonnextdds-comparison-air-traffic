Can you create a markdown design document outlining the main components and elements to implement the high_level_scenario.md
Make the description general independent of the middleware technology to be used. Later there will be specifc designs for technologies like RTI Connext DDS, gRPC, and Kafka.

Can you create a design document to implement the architecture_overview using RTI Connext DDS?

The system is not running so there no reading of live data. The Connext MCP should be used to help with the datamodes, Qos and DDS design patters/best practices.

I noticed there are no @nested annotations in teh datamodel. Can you add them as they are important to reduce codesize. Also @mutable is not used for teh types annotated with @topic. In general it is best practice to have those use @mutable, especially if they have a lot of optional members. This makes the datamodel more robust and evolvable. Can you update the design to correct this. Note that the @nested annotation applies only to only structures and unions not to enums.

Implement the dessign_connext_dds using python inside the connext_dds directory

Create a script that creates a local (project level) python environment alongside the requirements file with package dendencies

Is Lifespan a valid datareader Qos? It appears hghlighted as an error in the Qos profile file

Can you add a main to the run_scenario.sh that alloes me to start each invidudial application separately. The "all" option can start the whole scenario. Also create s script to stop all demo applications

Try running each individual application to ensure there are no errors. Use the python evironment "venv" under the workspace directory

Make the dashboard app a web-based UI I can run in my browser. Tech stack: Flask (single-file, render_template_string), Server-Sent Events , Inline HTML + CSS + vanilla JS (no external JS libraries).

Can you suggest a better UI for a demo?. One that shows aierplanwes flying, some maps, the airports involved, etc
Which of th esuggested technologies (Leaflet, Mapbox, Cesiium) would look better in a demo? Are there any usage restrictions in the free API keys?

Show the flight plan waypoints in the map when the flightplan or the flight are selected

Are the airplines following the waypoint in the flight plan. They do not seem to. Moreover the flight plans seem to terminate at points that are not airports

Add a control to the dashboard to speedup the simulation

What is the difference between the aircarft_id and the callsign?
Don't real aircraft also have some sort of inmutable ID?
Yes, use tail_number and make it look like the real ones. Also would it make sense to show it in the dashboard aircraft table?

In the dashboard next ro each flight there is a tag wuth the Callsign followed by some other string like "FL350" what is this extra string?
> That's the flight level — a standard aviation altitude reference. FL350 means Flight Level 350, which is 35,000 feet (altitude divided by 100, zero-padded to 3 digits). Matches how real ATC radar displays work.

The atc_types should be generated from the air_traffic.idl using rtiddsgen. Also the file two files should use the same name (except for the suffix). Can you fix the names and create a script to generate the python types from the IDL?

Is there a good way to show the centers and tracons, and the area they cover, in the dashboard? Is that typically disolayed in ATC dashboards?

