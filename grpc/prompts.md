I want to implement the same demo application using gRPC. Can you create a grpc directoty and write a grpc/DESIGN.md and grpc/air_traffic_types.proto that has the same individual application components (airplane, airport, tower, tracon, center, etc.) it will also be implememted in python

Is introducing an AirTrafficHub the way prople would implement this type of system with gRPC. Would they not connect directy to each data source wirh a streaming rpc to get the stream of updates?

Would static configuration of ports and applications to connect to be idiomatic in gRPC? I don't see how this would be made to work in an ATC system where flights and airplanes are dynamcally added to the system. How would people really do this wheh using grpc?

Why does Tower KLAX have a direct connection to TRACON90 same as Tower KJFK they are opposit eneds of teh country how can they share a TRACON?

Why are we making the app_flightplan_service double duty as a discovery service. This does not seem idomatic/realistic should we not use etcd or some other discovery service that is used typically with grpc?

Using etcd deployed via docker seems heavy. Would it be easier to create a python app that uses zeroconf ?

Generate the code to implement the design in grpc/DESIGN.md. Code generation isn’t complete until the code compiles error-free and passes basic functionality tests. As coding errors are corrected, log those errors and fixes in a file named grpc/LessonsLearned.md in the specs folder. 
Whenever you encounter an error that needs to be fixed, check the lessons learned file to see if you already know how to fix it.

Why do applications use a PORT_MAP variable? Discovery should be using zeroconf so port numbes should not appear in the python apps

There are 10 aircraft bun only 3 have flight plans

Flights are not being deviated when they encounter convective cells

Does this "sequential instruction" subscription problem appear for other streams?
