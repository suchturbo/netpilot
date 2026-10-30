# High CPU on a router or switch

Sustained control-plane CPU above about 80 percent slows routing updates, management access, and DHCP.

Common causes are a broadcast storm or switching loop, a flood of traffic punted to the CPU, a routing protocol that keeps flapping, or excessive logging. Look at recent logs for repeating messages first.

# When to reboot

A reboot clears the symptom but destroys the evidence. Collect logs and port counters first, and reboot only when the device is unmanageable or after the cause is understood.
