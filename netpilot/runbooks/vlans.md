# Moving a port to another VLAN

Changing a port's access VLAN moves the attached device to a different network segment. It will usually need a new DHCP lease and may lose access to services in its old VLAN.

Confirm the target VLAN exists on the uplink trunk before moving ports onto it, or the device will be cut off.
