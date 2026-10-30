# CRC and input errors on a port

Rising CRC or input errors usually mean a physical layer problem, not a configuration problem.

Check, in order: the patch cable (swap it first, it is the cheapest fix), the transceiver or the far-end NIC, and a duplex or speed mismatch between the two ends. Errors that climb only under load often point to a marginal cable run that is too long or damaged.

# Clearing and confirming

After replacing the cable, note the current error count and check again after some traffic has passed. A stable counter means the fix worked.
