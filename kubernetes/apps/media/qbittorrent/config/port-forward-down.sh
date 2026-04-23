#!/bin/sh
# Called by gluetun VPN_PORT_FORWARDING_DOWN_COMMAND when port forwarding is torn down.
wget -O- -nv --retry-connrefused \
  --post-data "json={\"listen_port\":0,\"current_network_interface\":\"lo\"}" \
  http://127.0.0.1:8080/api/v2/app/setPreferences
