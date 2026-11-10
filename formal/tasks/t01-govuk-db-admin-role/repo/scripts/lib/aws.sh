# Run a command in AWS as the given role.
#   run_as ROLE COMMAND [ARGS...]
run_as() {
  local role="$1"
  shift
  gds aws "$role" -- "$@"
}
