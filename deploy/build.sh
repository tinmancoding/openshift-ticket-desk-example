#!/bin/sh
set -eu
case "$COMPONENT" in api|renderer) ;; *) exit 1 ;; esac
case "$REVISION" in *[!0-9a-f]*) exit 1 ;; esac
test "${#REVISION}" -eq 40
config="desk-$COMPONENT"
build=$(oc start-build "$config" --commit="$REVISION" -o name)
printf '%s' "$build" > "$(results.build.path)"
echo "Started $build at $REVISION"
complete=false
for attempt in $(seq 1 180); do
  phase=$(oc get "$build" -o jsonpath='{.status.phase}')
  case "$phase" in
    Complete) complete=true; break ;;
    Failed|Error|Cancelled) oc logs "$build" || true; exit 1 ;;
  esac
  sleep 5
done
if [ "$complete" != true ]; then
  echo "Build still active: inspect/cancel $build before cleanup" >&2
  exit 1
fi
oc logs "$build"
actual=$(oc get "$build" -o jsonpath='{.spec.revision.git.commit}')
test "$actual" = "$REVISION"
digest=$(oc get "$build" -o jsonpath='{.status.output.to.imageDigest}')
case "$digest" in sha256:*) ;; *) exit 1 ;; esac
repository=$(oc get imagestream "$config" -o jsonpath='{.status.dockerImageRepository}')
test -n "$repository"
printf '%s@%s' "$repository" "$digest" > "$(results.image.path)"
