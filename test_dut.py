import logging
import nidmm
import time

logger = logging.getLogger(__name__)

some_value = 5

def test_to_run(target):
    # with nidmm.Session("Dev1") as session:
    #     print("Measurement: " + str(session.read()))
    logger.info(f"I received {target}.")
    time.sleep(1)
    return {"compare": target == 45, "other_output": "abc"}

def other_test():
    logger.info("I could also do this.")
    time.sleep(1)
    return {"some_return": True, "value": 3}

def range_test(value, min, max):
    return {"compare": min < value < max}
