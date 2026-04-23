#!/bin/sh
# Called by gluetun VPN_PORT_FORWARDING_UP_COMMAND when a forwarded port is assigned.
# Args: $1 = port, $2 = VPN interface name
wget -O- -nv --retry-connrefused \
  --post-data "json={\"listen_port\":$1,\"current_network_interface\":\"$2\",\"random_port\":false,\"upnp\":false}" \
  http://127.0.0.1:8080/api/v2/app/setPreferences
