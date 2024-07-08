import logging
import nidmm

logger = logging.getLogger(__name__)

some_value = 5

def test_to_run(target):
    # with nidmm.Session("Dev1") as session:
    #     print("Measurement: " + str(session.read()))
    logger.info(f"I received {target}.")
    return {"compare": target == 45, "other_output": "abc"}

def other_test(value):
    logger.info("I could also do this.")
    return {"some_return": True, "value": value}

def range_test(value, min, max):
    return {"compare": min < value < max}
