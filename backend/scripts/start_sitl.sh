#!/usr/bin/env bash
# Launch ArduPilot SITL: start_sitl.sh copter|plane  (set ARDUPILOT_ROOT to your checkout)
set -euo pipefail

VEHICLE="${1:-copter}"
ARDUPILOT_ROOT="${ARDUPILOT_ROOT:-$HOME/ardupilot}"
# sim_vehicle.py needs the system Python that ArduPilot's prereqs script set up
SITL_PYTHON="${SITL_PYTHON:-/usr/bin/python3}"
# waf's #!/usr/bin/env python3 shebang must also resolve to that interpreter
export PATH="/usr/bin:$PATH"

case "$VEHICLE" in
  copter) FRAME="quad" VTYPE="ArduCopter" ;;
  plane)  FRAME="plane" VTYPE="ArduPlane" ;;
  *) echo "Usage: $0 copter|plane" >&2; exit 1 ;;
esac

exec "$SITL_PYTHON" "$ARDUPILOT_ROOT/Tools/autotest/sim_vehicle.py" \
  -v "$VTYPE" -f "$FRAME" \
  --no-mavproxy \
  -w
