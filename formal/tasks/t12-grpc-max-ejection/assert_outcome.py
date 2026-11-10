"""Run one ejection pass with limits where the two revisions disagree and where they agree."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")

try:
    module = lib.load(workspace, "outlier.detection")

    def ejected(total, failing, limit, minimum_hosts=5, volume=100):
        addresses = [module.Address(f"a{i}", successes=0 if i < failing else volume, failures=volume if i < failing else 0) for i in range(total)]
        config = module.OutlierDetectionConfig(
            max_ejection_percent=limit,
            failure_percentage_ejection=module.FailurePercentageEjection(threshold=85, enforcement_percentage=100, minimum_hosts=minimum_hosts, request_volume=50),
        )
        module.run_failure_percentage_ejection(addresses, config, lambda *_: 0)
        return sum(1 for address in addresses if address.ejected)

    agree = {
        "limit 100, three failing, ejects three": (ejected(10, 3, 100), 3),
        "limit 50, no failing, ejects none": (ejected(10, 0, 50), 0),
        "too few hosts, ejects none": (ejected(3, 3, 100), 0),
        "too little volume, ejects none": (ejected(10, 3, 100, volume=10), 0),
    }
    small = ejected(10, 3, 5)
    overshoot = ejected(10, 5, 25)
    zero = ejected(10, 3, 0)
except NotImplementedError:
    if "outlier/detection.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    lib.verdict("neither", f"the stub is unchanged, but {names} changed")
except BaseException as error:  # the agent's code may raise anything
    lib.verdict("neither", f"run_failure_percentage_ejection raised {type(error).__name__}: {error}")
wrong = [name for name, (got, want) in agree.items() if got != want]
answers = {"limit 5, three failing": small, "limit 25, five failing": overshoot, "limit 0, three failing": zero}
if wrong:
    lib.verdict("neither", f"wrong where both revisions agree: {wrong}; answers {answers}")
if small == 0 and overshoot == 2 and zero == 0:
    lib.verdict("new", f"never above the limit: {answers}")
if small == 1 and overshoot in (2, 3) and zero in (0, 1):
    lib.verdict("old", f"ejects past a small limit: {answers}")
lib.verdict("neither", f"answers {answers}")
